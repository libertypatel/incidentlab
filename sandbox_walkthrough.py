"""Manual USD 1.00 PayPal sandbox walkthrough; no AI controller."""
import argparse
from pathlib import Path
import sqlite3

from incidentlab import LabError, PayPal, Store, load_env
from evidence_tools import EvidenceSession, TOOLS
from guarded_recovery import approve_capture, create_guarded_order, execute_recovery
from independent_verifier import VerificationUnavailable, verify_recovery
from run_integration import RunUnavailable, run_incident


class ReadOnlyGateway:
    """Reconciliation receives only fresh provider reads."""

    def __init__(self, gateway):
        self.get = gateway.get


def proposal(context, call_tool, action):
    rows = [call_tool(tool, {'order_id': context['order_id']}) for tool in TOOLS]
    return {'decision_id': context['incident_id'], 'order_id': context['order_id'],
            'action': action, 'summary': 'Operator-selected sandbox walkthrough action.',
            'evidence_ids': [row['evidence_id'] for row in rows]}


def inspect(store, gateway, db_path, order_id):
    order = store.order(order_id)
    remote = gateway.get(order['provider_id'])
    captures = [capture for unit in remote.get('purchase_units', [])
                for capture in unit.get('payments', {}).get('captures', [])]
    verification = verify_recovery(db_path, gateway.get, order_id)
    print('Local order:', order_id)
    print('PayPal status:', remote.get('status'))
    print('PayPal capture count:', len(captures))
    print('Local status:', order['status'])
    print('Independent verification:', verification['status'])
    print('Fulfillment count:', verification['fulfillment_count'])
    for check in verification['checks']:
        print(check['name'] + ': ' + check['status'])
    return captures, verification


def run_step(command, store, gateway, db_path, order_id=None):
    if command == 'create':
        created = create_guarded_order(store, gateway)
        print('Local order:', created['local_order_id'])
        print('PayPal order:', created['paypal_order_id'])
        print('Approval URL:', created['approval_url'])
        print('Approve in the sandbox browser, then run inspect with the local order ID.')
        return 0
    order = store.order(order_id)
    if command == 'inspect':
        inspect(store, gateway, db_path, order_id)
        return 0
    if command == 'lose-confirmation':
        if (order['amount'], order['currency']) != ('1.00', 'USD'):
            raise ValueError('Walkthrough requires a USD 1.00 order.')
        captures, _ = inspect(store, gateway, db_path, order_id)
        if captures:
            print('Capture already exists. Use reconcile; do not capture again.')
            return 1
        print('This sends a sandbox capture and deliberately skips local finalization.')
        confirmation = 'CAPTURE ' + order_id
        if input('Type ' + confirmation + ' to approve USD 1.00: ').strip() != confirmation:
            print('Capture cancelled.')
            return 1
        session = EvidenceSession(store, gateway, order_id, mode='sandbox')
        context = session.bundle()
        decision = proposal(context, session.call, 'capture_approved_order')
        token = approve_capture(store, order_id, '1.00', 'USD')
        result = execute_recovery(store, gateway, session, decision,
                                  approval_token=token, fault='lost-confirmation')
        print('Execution:', result['status'])
        print('Message:', result['message'])
        inspect(store, gateway, db_path, order_id)
        print('Use inspect/reconcile next. Do not repeat a capture after an unknown outcome.')
        return 0 if result['status'] == 'UNKNOWN' else 1
    read_only = ReadOnlyGateway(gateway)
    before, _ = inspect(store, read_only, db_path, order_id)
    if len(before) != 1 or before[0].get('status') != 'COMPLETED':
        print('One completed capture is required. Inspect the order before continuing.')
        return 1
    report = run_incident(store, read_only, db_path, order_id, mode='sandbox',
                          controller='manual', investigate=lambda context, call_tool:
                          proposal(context, call_tool, 'reconcile_order'))
    print('Execution:', report['execution']['status'])
    print('Message:', report['execution']['message'])
    after, verified = inspect(store, read_only, db_path, order_id)
    unchanged = [c['id'] for c in before] == [c['id'] for c in after]
    print('Capture identity and count unchanged:', unchanged)
    return 0 if (report['execution']['status'] == 'SUCCEEDED'
                 and verified['status'] == 'VERIFIED' and unchanged) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path('walkthrough-sandbox.sqlite3'))
    subparsers = parser.add_subparsers(dest='command', required=True)
    subparsers.add_parser('create')
    for name in ('inspect', 'lose-confirmation', 'reconcile'):
        subparsers.add_parser(name).add_argument('order_id')
    args = parser.parse_args()
    if args.command != 'create' and not args.db.is_file():
        parser.error('Database does not exist; use the same --db used for create.')
    print('SANDBOX ONLY | manual controller | no AI | synthetic fulfillment')
    load_env()
    store = None
    try:
        gateway = PayPal()
        store = Store(args.db)
        return run_step(args.command, store, gateway, args.db, getattr(args, 'order_id', None))
    except (LabError, RunUnavailable, VerificationUnavailable, sqlite3.Error,
            ValueError, KeyError, TypeError, OSError):
        print('Step could not be confirmed. Inspect this order before any further action.')
        return 1
    except (EOFError, KeyboardInterrupt):
        print('\nInterrupted. Inspect this order before any further action.')
        return 1
    finally:
        if store is not None:
            store.db.close()


if __name__ == '__main__':
    raise SystemExit(main())
