"""Behavior and leakage checks for the diagnostic boundary; offline only."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator, FormatChecker
from incidentlab import Store, new_order, capture
from evidence_tools import EvidenceSession, TOOLS
from demo_evidence import EvidenceFakePayPal, example


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.store, self.gateway = Store(':memory:'), EvidenceFakePayPal()
        created = new_order(self.store, self.gateway)
        self.local, self.remote = created['local_order_id'], created['paypal_order_id']
        self.gateway.approve(self.remote)
        self.session = EvidenceSession(self.store, self.gateway, self.local, mode='offline')

    def tearDown(self):
        self.store.db.close()

    def call(self, tool):
        return self.session.call(tool, {'order_id': self.local})

    def test_both_scenarios_match_schema_and_have_distinct_provider_evidence(self):
        schema = json.loads((Path(__file__).parent / 'contracts/incident-v1.schema.json').read_text())
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        bundles = [example(fault) for fault in ('before-submit', 'lost-confirmation')]
        for bundle in bundles:
            validator.validate(bundle)
            self.assertEqual(bundle['observations'][0]['data']['payment_state'], 'UNCONFIRMED')
        self.assertEqual(bundles[0]['observations'][1]['data']['captures'], [])
        self.assertEqual(bundles[1]['observations'][1]['data']['captures'][0]['status'], 'COMPLETED')

    def test_private_fields_and_injected_event_text_are_not_exposed(self):
        capture(self.store, self.gateway, self.local, 'before-submit')
        self.store.event(self.local, 'secret_kind', 'SECRET_CANARY injected lost-confirmation')
        self.gateway.orders[self.remote]['payer'] = {'email_address': 'SECRET_CANARY'}
        for tool in TOOLS:
            self.call(tool)
        output = json.dumps(self.session.bundle())
        for forbidden in ('SECRET_CANARY', 'capture_key', 'create_key', 'before-submit', 'lost-confirmation', 'BLOCKED'):
            self.assertNotIn(forbidden, output)
        self.assertNotIn(self.store.order(self.local)['capture_key'], output)

    def test_reads_do_not_mutate_database_or_capture(self):
        before = list(self.store.db.iterdump())
        for tool in TOOLS:
            self.call(tool)
        self.assertEqual(before, list(self.store.db.iterdump()))
        self.assertEqual(self.gateway.capture_calls, 0)

    def test_invalid_requests_do_not_access_provider(self):
        with patch.object(self.gateway, 'get') as get:
            for tool, args in [('capture', {'order_id': self.local}), ('get_paypal_order', {'order_id': 'other'}), ('get_paypal_order', {'order_id': self.local, 'url': 'other'})]:
                with self.assertRaises(ValueError):
                    self.session.call(tool, args)
            get.assert_not_called()

    def test_provider_errors_are_sanitized_and_not_empty_capture_evidence(self):
        for error in (TimeoutError('SECRET_CANARY'), ValueError('SECRET_CANARY')):
            with patch.object(self.gateway, 'get', side_effect=error):
                result = self.call('get_paypal_order')
            self.assertEqual(result['status'], 'ERROR')
            self.assertNotIn('data', result)
            self.assertNotIn('SECRET_CANARY', json.dumps(result))

    def test_mismatch_is_preserved_and_malformed_response_rejected(self):
        unit = self.gateway.orders[self.remote]['purchase_units'][0]
        unit['custom_id'] = 'different-order'
        unit['amount']['value'] = '2.00'
        result = self.call('get_paypal_order')['data']['purchase_unit']
        self.assertEqual(result['custom_id'], 'different-order')
        self.assertEqual(result['amount'], '2.00')
        del unit['amount']
        self.assertEqual(self.call('get_paypal_order')['status'], 'ERROR')

    def test_missing_logs_never_claim_not_sent(self):
        self.store.db.execute('DELETE FROM events')
        self.store.db.commit()
        self.assertEqual(self.call('get_application_events')['data'], {'coverage': 'PARTIAL', 'events': []})

    def test_untrusted_callers_cannot_modify_saved_transcript(self):
        result = self.call('get_local_order')
        result['data']['payment_state'] = 'PAID'
        bundle = self.session.bundle()
        bundle['observations'].clear()
        self.assertEqual(self.session.bundle()['observations'][0]['data']['payment_state'], 'UNCONFIRMED')

    def test_corrupt_local_state_is_not_normalized(self):
        self.store.state(self.local, 'CORRUPT')
        self.assertEqual(self.call('get_local_order')['status'], 'ERROR')


if __name__ == '__main__':
    unittest.main()
