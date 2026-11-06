"""Offline evidence walkthrough. Fake provider; no AI or network requests."""
import json
from incidentlab import Store, new_order, capture
from evidence_tools import EvidenceSession, TOOLS
from test_recovery import FakePayPal


class EvidenceFakePayPal(FakePayPal):
    def create(self, local_id, request_id):
        result = super().create(local_id, request_id)
        self.orders[result['id']]['purchase_units'][0]['amount'] = {'value': '1.00', 'currency_code': 'USD'}
        return self.get(result['id'])


def example(fault):
    store, gateway = Store(':memory:'), EvidenceFakePayPal()
    try:
        created = new_order(store, gateway)
        local_id = created['local_order_id']
        gateway.approve(created['paypal_order_id'])
        capture(store, gateway, local_id, fault)
        session = EvidenceSession(store, gateway, local_id, mode='offline')
        for tool in TOOLS:
            session.call(tool, {'order_id': local_id})
        return session.bundle()
    finally:
        store.db.close()


if __name__ == '__main__':
    # Labels below belong to the human demo, never the investigator's input.
    print('OFFLINE SIMULATION: fake provider; no AI or PayPal requests.')
    for fault in ('before-submit', 'lost-confirmation'):
        print(json.dumps(example(fault), indent=2))
