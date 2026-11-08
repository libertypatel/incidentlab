"""Bounded recovery executor. All new lab mutations must use this entry point."""
from contextlib import contextmanager
from datetime import datetime, timezone
import secrets
import sqlite3
import time
import uuid

from incidentlab import LabError, new_order, payment_evidence


class GuardBlocked(Exception):
    pass


def initialize(store):
    store.db.executescript('''
      CREATE TABLE IF NOT EXISTS capture_journal (
        order_id TEXT PRIMARY KEY, provider_id TEXT NOT NULL, amount TEXT NOT NULL,
        currency TEXT NOT NULL, request_key TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('UNSENT','POSSIBLY_SENT','CONFIRMED')));
      CREATE TABLE IF NOT EXISTS recovery_claims (
        order_id TEXT PRIMARY KEY, owner TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS recovery_runs (
        incident_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, order_id TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS capture_approvals (
        token TEXT PRIMARY KEY, order_id TEXT NOT NULL, provider_id TEXT NOT NULL,
        amount TEXT NOT NULL, currency TEXT NOT NULL, expires REAL NOT NULL,
        used INTEGER NOT NULL DEFAULT 0);
    ''')


def create_guarded_order(store, gateway):
    """Register only newly created orders, never infer UNSENT for old orders."""
    initialize(store)
    created = new_order(store, gateway)
    order = store.order(created['local_order_id'])
    with store.db:
        store.db.execute('INSERT INTO capture_journal VALUES (?,?,?,?,?,?)', (
            order['id'], order['provider_id'], order['amount'], order['currency'], order['capture_key'], 'UNSENT'))
    return created


def approve_capture(store, order_id, amount, currency):
    """Trusted operator UI only. Do not expose this function as an agent tool."""
    initialize(store)
    order = store.order(order_id)
    if amount != order['amount'] or currency != order['currency']:
        raise GuardBlocked('Approval amount or currency does not match.')
    token = secrets.token_urlsafe(32)
    with store.db:
        store.db.execute('INSERT INTO capture_approvals VALUES (?,?,?,?,?,?,0)', (
            token, order_id, order['provider_id'], amount, currency, time.time() + 300))
    return token


@contextmanager
def _claim(store, order_id):
    # Persistent per-order ownership works across processes. No timed takeover:
    # a crashed worker may have sent a request and needs operator investigation.
    owner = uuid.uuid4().hex
    try:
        with store.db:
            store.db.execute('INSERT INTO recovery_claims VALUES (?,?)', (order_id, owner))
    except sqlite3.IntegrityError:
        raise GuardBlocked('Another recovery owns this order; inspect before retrying.') from None
    try:
        yield
    finally:
        with store.db:
            store.db.execute('DELETE FROM recovery_claims WHERE order_id=? AND owner=?', (order_id, owner))


def _validate_proposal(session, decision):
    expected = {'decision_id', 'action', 'order_id', 'summary', 'evidence_ids'}
    if not isinstance(decision, dict) or set(decision) != expected:
        raise GuardBlocked('Unsupported proposal shape.')
    for key in ('decision_id', 'summary', 'order_id'):
        if not isinstance(decision[key], str) or not decision[key]:
            raise GuardBlocked('Invalid proposal field.')
    if decision['action'] not in {'capture_approved_order', 'reconcile_order', 'escalate'}:
        raise GuardBlocked('Unsupported recovery action.')
    bundle = session.bundle()  # Trusted session, not an agent-supplied bundle.
    if decision['order_id'] != bundle['order_id']:
        raise GuardBlocked('Proposal order does not match the investigation.')
    ids = decision['evidence_ids']
    if not isinstance(ids, list) or not ids or any(not isinstance(v, str) for v in ids) or len(ids) != len(set(ids)):
        raise GuardBlocked('Invalid evidence references.')
    evidence = {row['evidence_id']: row for row in bundle['observations']}
    for reference in ids:
        if reference not in evidence:
            raise GuardBlocked('Evidence reference is not in the trusted transcript.')
        try:
            observed = datetime.fromisoformat(evidence[reference]['observed_at'].replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - observed).total_seconds()
        except (KeyError, ValueError, TypeError):
            raise GuardBlocked('Evidence timestamp is invalid.') from None
        if not -5 <= age <= 300:
            raise GuardBlocked('Evidence is stale; investigate again.')
    return bundle['order_id']


def _check_unit(order, remote):
    # Recovery may reuse recovery parsing; the verifier remains independent.
    units = remote.get('purchase_units')
    if remote.get('id') != order['provider_id'] or not isinstance(units, list) or len(units) != 1:
        raise GuardBlocked('Provider order identity is not established.')
    unit = units[0]
    if unit.get('custom_id') != order['id'] or unit.get('amount') != {'value': order['amount'], 'currency_code': order['currency']}:
        raise GuardBlocked('Provider identity, amount, or currency does not match.')
    payments = unit.get('payments', {})
    if not isinstance(payments, dict) or payments.get('refunds'):
        raise GuardBlocked('Refunded or unsupported payment evidence.')
    captures = payments.get('captures', [])
    if not isinstance(captures, list):
        raise GuardBlocked('Capture evidence is malformed.')
    return captures


def _finalize(store, gateway, order_id):
    order = store.order(order_id)
    remote = gateway.get(order['provider_id'])
    _check_unit(order, remote)
    completed = payment_evidence(order, remote)
    if not completed:
        raise GuardBlocked('A matching completed capture is required.')
    with store.db:
        existing = store.db.execute('SELECT capture_id FROM fulfillment WHERE order_id=?', (order_id,)).fetchone()
        if existing and existing['capture_id'] != completed:
            raise GuardBlocked('Conflicting fulfillment reference.')
        store.db.execute('INSERT OR IGNORE INTO fulfillment VALUES (?,?)', (order_id, completed))
        store.db.execute("UPDATE orders SET status='PAID',capture_id=? WHERE id=?", (completed, order_id))
        store.db.execute("UPDATE capture_journal SET state='CONFIRMED' WHERE order_id=?", (order_id,))


def _reserve_capture(store, order, approval_token):
    journal = store.db.execute('SELECT * FROM capture_journal WHERE order_id=?', (order['id'],)).fetchone()
    if journal is None or journal['state'] != 'UNSENT':
        raise GuardBlocked('Durable proof of non-submission is unavailable; do not recapture.')
    for field, local in (('provider_id', 'provider_id'), ('amount', 'amount'), ('currency', 'currency'), ('request_key', 'capture_key')):
        if journal[field] != order[local]:
            raise GuardBlocked('Capture journal no longer matches the order.')
    # Legacy CLI writes are outside the guarded path. Never adopt their attempts.
    if order['status'] not in {'AWAITING_APPROVAL', 'BLOCKED'} or store.db.execute(
            "SELECT 1 FROM events WHERE order_id=? AND kind='capture_started' LIMIT 1", (order['id'],)).fetchone():
        raise GuardBlocked('An earlier capture attempt cannot be excluded.')
    approval = store.db.execute('SELECT * FROM capture_approvals WHERE token=?', (approval_token,)).fetchone()
    if not approval or approval['used'] or approval['expires'] <= time.time() or any(
            approval[key] != order[key] for key in ('provider_id', 'amount', 'currency')) or approval['order_id'] != order['id']:
        raise GuardBlocked('Fresh operator approval for this order and amount is required.')
    # Both records commit before network I/O. A crash afterward stays uncertain.
    with store.db:
        store.db.execute("UPDATE capture_journal SET state='POSSIBLY_SENT' WHERE order_id=?", (order['id'],))
        store.db.execute('UPDATE capture_approvals SET used=1 WHERE token=?', (approval_token,))
        store.db.execute("UPDATE orders SET status='UNKNOWN' WHERE id=?", (order['id'],))
    return journal['request_key']


def execute_recovery(store, gateway, session, decision, *, approval_token=None, fault='none'):
    """One proposal per call. fault is a trusted harness option, never model input.

    SUCCEEDED reports execution, not independently verified recovery. Use the
    separate verifier after this call. Approval tokens must not enter model logs.
    """
    sent = False
    action = decision.get('action') if isinstance(decision, dict) else None
    decision_id = decision.get('decision_id') if isinstance(decision, dict) else None
    def result(status, message):
        return {'decision_id': decision_id, 'action': action, 'status': status, 'message': message}
    try:
        order_id = _validate_proposal(session, decision)
        if fault not in {'none', 'lost-confirmation'}:
            raise GuardBlocked('Unsupported harness option.')
        if action == 'escalate':
            return result('NOT_EXECUTED', 'Escalated for operator investigation; no recovery performed.')
        initialize(store)
        with _claim(store, order_id):
            try:
                with store.db:
                    store.db.execute('INSERT INTO recovery_runs VALUES (?,?,?)', (
                        session.bundle()['incident_id'], decision_id, order_id))
            except sqlite3.IntegrityError:
                raise GuardBlocked('This investigation already attempted a recovery; start a fresh investigation.') from None
            if action == 'reconcile_order':
                _finalize(store, gateway, order_id)
            else:
                order = store.order(order_id)
                remote = gateway.get(order['provider_id'])
                captures = _check_unit(order, remote)
                if remote.get('status') != 'APPROVED' or captures:
                    raise GuardBlocked('Capture requires fresh buyer approval and no existing captures.')
                key = _reserve_capture(store, order, approval_token)
                sent = True  # May have been sent from this point onward.
                gateway.capture(order['provider_id'], key)
                if fault == 'lost-confirmation':
                    return result('UNKNOWN', 'Capture outcome requires fresh investigation; local confirmation unavailable.')
                _finalize(store, gateway, order_id)
        return result('SUCCEEDED', 'Recovery executed; independent verification is required.')
    except GuardBlocked as exc:
        return result('UNKNOWN' if sent else 'BLOCKED', str(exc))
    except (LabError, OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError):
        return result('UNKNOWN' if sent else 'FAILED', 'Recovery could not be confirmed; investigate before retrying.')
