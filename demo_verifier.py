"""Offline independent verification walkthrough. No AI or network requests."""
import json
from pathlib import Path
import tempfile
from incidentlab import Store, new_order, capture, reconcile
from test_recovery import FakePayPal
from independent_verifier import verify_recovery


def main():
    print('OFFLINE SIMULATION: fake provider; no AI or PayPal requests.')
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'demo.sqlite3'
        store, gateway = Store(path), FakePayPal()
        try:
            created = new_order(store, gateway)
            local, remote = created['local_order_id'], created['paypal_order_id']
            gateway.orders[remote]['purchase_units'][0]['amount'] = {'value': '1.00', 'currency_code': 'USD'}
            gateway.approve(remote)
            capture(store, gateway, local, 'lost-confirmation')
            print('Before recovery:')
            print(json.dumps(verify_recovery(path, gateway.get, local), indent=2))
            reconcile(store, gateway, local)
            print('After recovery:')
            print(json.dumps(verify_recovery(path, gateway.get, local), indent=2))
            print('Provider capture calls:', gateway.capture_calls)
            def unavailable(_):
                raise TimeoutError('simulated provider outage')
            print('Provider unavailable:')
            print(json.dumps(verify_recovery(path, unavailable, local), indent=2))
        finally:
            store.db.close()


if __name__ == '__main__':
    main()
