"""Offline manual-controller walkthrough; no AI or PayPal requests."""
from pathlib import Path
import tempfile
from incidentlab import Store
from evidence_tools import EvidenceSession, TOOLS
from independent_verifier import verify_recovery
from guarded_recovery import create_guarded_order, approve_capture, execute_recovery
from test_guarded_recovery import GuardedFake


def propose(store, gateway, local_id, action):
    session = EvidenceSession(store, gateway, local_id, mode='offline')
    ids = [session.call(tool, {'order_id': local_id})['evidence_id'] for tool in TOOLS]
    decision = {'decision_id': session.bundle()['incident_id'], 'action': action,
                'order_id': local_id, 'summary': 'Manual offline demonstration.', 'evidence_ids': ids}
    return session, decision


def main():
    print('OFFLINE SIMULATION: fake provider; manual controller; no AI or PayPal requests.')
    with tempfile.TemporaryDirectory() as folder:
        for fault in ('before-submit', 'lost-confirmation'):
            path = Path(folder) / (fault + '.sqlite3')
            store, gateway = Store(path), GuardedFake()
            try:
                created = create_guarded_order(store, gateway)
                local_id = created['local_order_id']
                gateway.approve(created['paypal_order_id'])
                if fault == 'before-submit':
                    # Controlled checkout failure before capture entry. UNSENT
                    # comes from registration, never inferred from missing logs.
                    store.state(local_id, 'BLOCKED')
                else:
                    session, decision = propose(store, gateway, local_id, 'capture_approved_order')
                    token = approve_capture(store, local_id, '1.00', 'USD')
                    execute_recovery(store, gateway, session, decision, approval_token=token, fault=fault)
                print('\nHuman demo label:', fault)
                print('Customer: Checkout could not be confirmed')
                print('Before recovery:', verify_recovery(path, gateway.get, local_id)['status'])
                action = 'capture_approved_order' if fault == 'before-submit' else 'reconcile_order'
                # Chosen by a human here. Investigator integration comes later.
                session, decision = propose(store, gateway, local_id, action)
                token = approve_capture(store, local_id, '1.00', 'USD') if fault == 'before-submit' else None
                result = execute_recovery(store, gateway, session, decision, approval_token=token)
                print('Manual proposal:', action)
                print('Execution:', result['status'])
                print('Independent verification:', verify_recovery(path, gateway.get, local_id)['status'])
                print('Provider capture calls:', gateway.capture_calls)
            finally:
                store.db.close()


if __name__ == '__main__':
    main()
