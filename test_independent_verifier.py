"""Verifier behavior tests. Fake provider only; no PayPal requests."""
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator
from incidentlab import Store, new_order, capture, reconcile
from test_recovery import FakePayPal
from independent_verifier import verify_recovery, VerificationUnavailable, _open_readonly


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'lab.sqlite3'
        self.store, self.gateway = Store(self.path), FakePayPal()
        created = new_order(self.store, self.gateway)
        self.local, self.remote = created['local_order_id'], created['paypal_order_id']
        self.gateway.orders[self.remote]['purchase_units'][0]['amount'] = {'value': '1.00', 'currency_code': 'USD'}
        self.gateway.approve(self.remote)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def verify(self, fetch=None):
        return verify_recovery(self.path, fetch or self.gateway.get, self.local)

    def paid(self):
        capture(self.store, self.gateway, self.local)

    def test_paid_order_verifies_and_matches_contract(self):
        self.paid()
        result = self.verify()
        schema = json.loads((Path(__file__).parent / 'contracts/incident-v1.schema.json').read_text())
        schema = {**schema, 'oneOf': [{'$ref': '#/$defs/verification'}]}
        Draft202012Validator(schema).validate(result)
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertTrue(all(check['status'] == 'PASS' for check in result['checks']))

    def test_approval_is_not_payment(self):
        self.assertEqual(self.verify()['status'], 'NOT_VERIFIED')

    def test_lost_confirmation_is_not_repaired_by_verifier(self):
        capture(self.store, self.gateway, self.local, 'lost-confirmation')
        before = list(self.store.db.iterdump())
        self.assertEqual(self.verify()['status'], 'NOT_VERIFIED')
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual(self.gateway.capture_calls, 1)
        reconcile(self.store, self.gateway, self.local)
        self.assertEqual(self.verify()['status'], 'VERIFIED')

    def test_missing_fulfillment_fails(self):
        self.paid()
        self.store.db.execute('DELETE FROM fulfillment')
        self.store.db.commit()
        self.assertEqual(self.verify()['status'], 'NOT_VERIFIED')

    def test_wrong_order_or_amount_fails(self):
        self.paid()
        original = deepcopy(self.gateway.orders[self.remote])
        for field in ('id', 'custom_id', 'amount', 'currency'):
            remote = deepcopy(original)
            if field == 'id': remote['id'] = 'other'
            elif field == 'custom_id': remote['purchase_units'][0]['custom_id'] = 'other'
            elif field == 'amount': remote['purchase_units'][0]['payments']['captures'][0]['amount']['value'] = '2.00'
            else: remote['purchase_units'][0]['payments']['captures'][0]['amount']['currency_code'] = 'EUR'
            self.assertEqual(self.verify(lambda _: remote)['status'], 'NOT_VERIFIED', field)

    def test_pending_and_refunded_are_not_verified(self):
        self.paid()
        for status in ('PENDING', 'REFUNDED', 'PARTIALLY_REFUNDED'):
            self.gateway.orders[self.remote]['purchase_units'][0]['payments']['captures'][0]['status'] = status
            self.assertEqual(self.verify()['status'], 'NOT_VERIFIED')

    def test_timeout_and_malformed_response_are_inconclusive(self):
        self.paid()
        for response in (None, {}, {'id': self.remote}, {'unexpected': 'SECRET_CANARY'}):
            result = self.verify(lambda _: response)
            self.assertEqual(result['status'], 'INCONCLUSIVE')
            self.assertNotIn('SECRET_CANARY', json.dumps(result))
        def timeout(_):
            raise TimeoutError('SECRET_CANARY')
        self.assertEqual(self.verify(timeout)['status'], 'INCONCLUSIVE')

    def test_fetch_is_fresh_each_time(self):
        self.paid()
        with patch.object(self.gateway, 'get', wraps=self.gateway.get) as get:
            self.assertEqual(self.verify()['status'], 'VERIFIED')
            self.gateway.orders[self.remote]['purchase_units'][0]['payments']['captures'][0]['status'] = 'REFUNDED'
            self.assertEqual(self.verify()['status'], 'NOT_VERIFIED')
            self.assertEqual(get.call_count, 2)

    def test_database_connection_refuses_writes(self):
        connection = _open_readonly(self.path)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE orders SET status='PAID'")
        finally:
            connection.close()

    def test_missing_database_or_order_does_not_create_data(self):
        missing = Path(self.temp.name) / 'missing.sqlite3'
        with self.assertRaises(VerificationUnavailable):
            verify_recovery(missing, self.gateway.get, self.local)
        self.assertFalse(missing.exists())
        with self.assertRaises(VerificationUnavailable):
            verify_recovery(self.path, self.gateway.get, 'missing')

    def test_recovery_parser_is_not_used(self):
        self.paid()
        with patch('incidentlab.payment_evidence', side_effect=AssertionError('shared parser used')):
            self.assertEqual(self.verify()['status'], 'VERIFIED')

    def test_multiple_captures_are_inconclusive(self):
        self.paid()
        captures = self.gateway.orders[self.remote]['purchase_units'][0]['payments']['captures']
        captures.append({**deepcopy(captures[0]), 'id': 'another-capture'})
        self.assertEqual(self.verify()['status'], 'INCONCLUSIVE')

    def test_local_identity_change_during_fetch_is_inconclusive(self):
        self.paid()
        def changed(provider_id):
            result = self.gateway.get(provider_id)
            self.store.db.execute("UPDATE orders SET amount='2.00' WHERE id=?", (self.local,))
            self.store.db.commit()
            return result
        self.assertEqual(self.verify(changed)['status'], 'INCONCLUSIVE')


if __name__ == '__main__':
    unittest.main()
