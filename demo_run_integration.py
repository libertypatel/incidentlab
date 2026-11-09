"""Generate synthetic report inputs; no AI or PayPal requests."""
import argparse
import json
from pathlib import Path
import tempfile

from incidentlab import Store
from evidence_tools import TOOLS
from guarded_recovery import create_guarded_order, approve_capture, execute_recovery
from demo_guarded_recovery import propose
from test_guarded_recovery import GuardedFake
from run_integration import run_incident


def manual_investigator(context, call_tool):
    rows = [call_tool(tool, {'order_id': context['order_id']}) for tool in TOOLS]
    provider = rows[1]
    action = 'escalate'
    if all(row['status'] == 'OK' for row in rows):
        data = provider['data']
        if data['captures']:
            action = 'reconcile_order'
        elif (data['status'] == 'APPROVED' and any(
                event['event'] == 'CAPTURE_NOT_SENT' for event in rows[2]['data']['events'])):
            action = 'capture_approved_order'
    return {'decision_id': context['incident_id'], 'order_id': context['order_id'],
            'action': action, 'summary': 'Manual offline controller using diagnostic evidence.',
            'evidence_ids': [row['evidence_id'] for row in rows]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    output = args.output_dir or Path(tempfile.mkdtemp(prefix='incidentlab-reports-'))
    output.mkdir(parents=True, exist_ok=True)
    print('OFFLINE SIMULATION: manual controller, fake provider; no AI or PayPal requests.')
    with tempfile.TemporaryDirectory() as folder:
        for fault in ('before-submit', 'lost-confirmation'):
            path = Path(folder) / (fault + '.sqlite3')
            store, gateway = Store(path), GuardedFake()
            try:
                created = create_guarded_order(store, gateway)
                local_id = created['local_order_id']
                gateway.approve(created['paypal_order_id'])
                if fault == 'before-submit':
                    store.state(local_id, 'BLOCKED')
                else:
                    session, decision = propose(store, gateway, local_id, 'capture_approved_order')
                    token = approve_capture(store, local_id, '1.00', 'USD')
                    execute_recovery(store, gateway, session, decision,
                                     approval_token=token, fault='lost-confirmation')
                # Simulated operator approval is permitted only in this fake-provider demo.
                report = run_incident(store, gateway, path, local_id, mode='offline',
                    controller='manual', investigate=manual_investigator,
                    request_approval=lambda oid, amount, currency: approve_capture(store, oid, amount, currency))
                destination = output / (fault + '.json')
                destination.write_text(json.dumps(report, indent=2) + '\n')
                print(f"{fault}: {report['decision']['action']} / {report['execution']['status']} / "
                      f"{report['verification']['status']} / captures={gateway.capture_calls}")
                print(destination)
            finally:
                store.db.close()


if __name__ == '__main__':
    main()
