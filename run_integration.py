"""Contract v1 coordinator; investigators receive only bounded diagnostic tools."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

from jsonschema import Draft202012Validator, FormatChecker
from evidence_tools import EvidenceSession
from guarded_recovery import execute_recovery
from independent_verifier import verify_recovery, VerificationUnavailable


class RunUnavailable(Exception):
    """No complete run report is available; never implies recovery succeeded."""


def _validator(kind):
    schema = json.loads((Path(__file__).parent / 'contracts/incident-v1.schema.json').read_text())
    return Draft202012Validator({'$ref': '#/$defs/' + kind, '$defs': schema['$defs']},
                               format_checker=FormatChecker())


def run_incident(store, gateway, db_path, order_id, *, mode, controller,
                 investigate, request_approval=None, max_tool_calls=6):
    """investigate(context, call_tool) returns one contract decision.

    request_approval(order_id, amount, currency) is trusted operator application
    code returning a token or None. It is never offered as an investigator tool.
    controller and mode describe the actual application, not model assertions.
    """
    database = store.db.execute('PRAGMA database_list').fetchone()[2]
    if (mode not in {'offline', 'sandbox'} or controller not in {'manual', 'rules', 'agent'}
            or type(max_tool_calls) is not int or not 1 <= max_tool_calls <= 12
            or not database or Path(database).resolve() != Path(db_path).resolve()):
        raise RunUnavailable('Invalid run configuration or verification database.')
    session = EvidenceSession(store, gateway, order_id, mode=mode)
    context = {key: value for key, value in session.bundle().items() if key != 'observations'}
    attempts, rejected = 0, False

    def call_tool(tool, arguments):
        nonlocal attempts, rejected
        attempts += 1
        try:
            if attempts > max_tool_calls:
                raise ValueError('Diagnostic tool budget exceeded.')
            return session.call(tool, arguments)
        except Exception:
            rejected = True  # A controller cannot catch a violation and continue to execution.
            raise RunUnavailable('Diagnostic request rejected.') from None

    try:
        decision = deepcopy(investigate(deepcopy(context), call_tool))
        evidence = session.bundle()  # Snapshot before any recovery changes.
        _validator('evidence_bundle').validate(evidence)
        _validator('decision').validate(decision)
        references = {row['evidence_id'] for row in evidence['observations']}
        if (rejected or decision['order_id'] != order_id
                or not set(decision['evidence_ids']) <= references):
            raise ValueError('Invalid investigation')
    except Exception:
        raise RunUnavailable('Investigation failed validation; no recovery was attempted.') from None

    token = None
    if decision['action'] == 'capture_approved_order' and request_approval is not None:
        try:
            order = store.order(order_id)
            token = request_approval(order_id, order['amount'], order['currency'])
        except Exception:
            raise RunUnavailable('Operator approval was unavailable; no recovery was attempted.') from None
    execution = execute_recovery(store, gateway, session, decision, approval_token=token)
    try:
        verification = verify_recovery(db_path, gateway.get, order_id)
    except VerificationUnavailable:
        # Execution may already have occurred. Never imply this error is safe to retry.
        raise RunUnavailable('Post-execution verification unavailable; inspect before retrying.') from None

    timeline = []
    def record(stage, summary, ids=()):
        timeline.append({'sequence': len(timeline) + 1, 'stage': stage,
                         'summary': summary, 'evidence_ids': list(ids)})
    record('detected', evidence['symptom'])
    for row in evidence['observations']:
        record('tool_result', row['tool'] + ': ' + row['status'], [row['evidence_id']])
    record('decision', decision['summary'], decision['evidence_ids'])
    record('execution', execution['status'] + ': ' + execution['message'])
    record('verification', verification['status'])
    report = {'contract_version': '1.0', 'run_id': str(uuid.uuid4()), 'controller': controller,
              'evidence': evidence, 'decision': decision, 'execution': execution,
              'verification': verification, 'timeline': timeline}
    try:
        _validator('incident_run').validate(report)
    except Exception:
        raise RunUnavailable('Post-execution report invalid; inspect before retrying.') from None
    return report
