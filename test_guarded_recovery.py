"""Offline executor behavior, durable uncertainty, and concurrency checks."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator
from incidentlab import Store, new_order, capture
from evidence_tools import EvidenceSession, TOOLS
from independent_verifier import verify_recovery
from guarded_recovery import (create_guarded_order, approve_capture, execute_recovery,
                              _claim)
from test_recovery import FakePayPal


class GuardedFake(FakePayPal):
    def create(self, local_id, request_id):
        created = super().create(local_id, request_id)
        self.orders[created['id']]['purchase_units'][0]['amount'] = {'value': '1.00', 'currency_code': 'USD'}
        return self.get(created['id'])


class GuardedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'lab.sqlite3'
        self.store, self.gateway = Store(self.path), GuardedFake()
        created = create_guarded_order(self.store, self.gateway)
        self.local, self.remote = created['local_order_id'], created['paypal_order_id']
        self.gateway.approve(self.remote)

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def investigate(self, action='capture_approved_order'):
        session = EvidenceSession(self.store, self.gateway, self.local, mode='offline')
        ids = [session.call(tool, {'order_id': self.local})['evidence_id'] for tool in TOOLS]
        decision = {'decision_id': session.bundle()['incident_id'], 'order_id': self.local,
                    'action': action, 'summary': 'Offline test proposal.', 'evidence_ids': ids}
        return session, decision

    def run_action(self, action='capture_approved_order', token=None, fault='none'):
        session, decision = self.investigate(action)
        return execute_recovery(self.store, self.gateway, session, decision, approval_token=token, fault=fault)

    def approve(self):
        return approve_capture(self.store, self.local, '1.00', 'USD')

    def test_one_mutating_proposal_attempt_per_investigation(self):
        session, decision = self.investigate()
        token = self.approve()
        first = execute_recovery(self.store, self.gateway, session, decision, approval_token=token)
        self.assertEqual(first['status'], 'SUCCEEDED')
        second = execute_recovery(self.store, self.gateway, session, decision, approval_token=token)
        self.assertEqual(second['status'], 'BLOCKED')
        self.assertEqual(self.gateway.capture_calls, 1)

    def test_capture_requires_separate_operator_approval(self):
        self.assertEqual(self.run_action()['status'], 'BLOCKED')
        self.assertEqual(self.gateway.capture_calls, 0)
        self.assertEqual(self.run_action(token=self.approve())['status'], 'SUCCEEDED')
        self.assertEqual(verify_recovery(self.path, self.gateway.get, self.local)['status'], 'VERIFIED')

    def test_lost_confirmation_reconciles_without_recapture(self):
        self.assertEqual(self.run_action(token=self.approve(), fault='lost-confirmation')['status'], 'UNKNOWN')
        self.assertEqual(self.run_action(token=self.approve())['status'], 'BLOCKED')
        self.assertEqual(self.run_action('reconcile_order')['status'], 'SUCCEEDED')
        self.assertEqual(self.run_action('reconcile_order')['status'], 'SUCCEEDED')
        self.assertEqual(self.gateway.capture_calls, 1)
        self.assertEqual(verify_recovery(self.path, self.gateway.get, self.local)['fulfillment_count'], 1)

    def test_timeout_is_durable_across_database_reopen(self):
        self.gateway.lose_transport_response = True
        self.assertEqual(self.run_action(token=self.approve())['status'], 'UNKNOWN')
        self.store.db.close()
        self.store = Store(self.path)
        state = self.store.db.execute('SELECT state FROM capture_journal WHERE order_id=?', (self.local,)).fetchone()[0]
        self.assertEqual(state, 'POSSIBLY_SENT')
        self.assertEqual(self.run_action(token=self.approve())['status'], 'BLOCKED')
        self.assertEqual(self.run_action('reconcile_order')['status'], 'SUCCEEDED')
        self.assertEqual(self.gateway.capture_calls, 1)

    def test_pre_dispatch_crash_window_blocks_retry_even_without_capture(self):
        def failed(order_id, request_id):
            raise TimeoutError('SECRET_CANARY')
        with patch.object(self.gateway, 'capture', side_effect=failed):
            result = self.run_action(token=self.approve())
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertNotIn('SECRET_CANARY', json.dumps(result))
        self.assertEqual(self.run_action(token=self.approve())['status'], 'BLOCKED')
        self.assertEqual(self.gateway.capture_calls, 0)

    def test_existing_orders_are_not_backfilled_as_unsent(self):
        created = new_order(self.store, self.gateway)
        self.local, self.remote = created['local_order_id'], created['paypal_order_id']
        self.gateway.approve(self.remote)
        self.assertEqual(self.run_action(token=self.approve())['status'], 'BLOCKED')
        self.assertEqual(self.gateway.capture_calls, 0)

    def test_approval_is_bound_to_order_and_expires(self):
        token = self.approve()
        with self.store.db:
            self.store.db.execute('UPDATE capture_approvals SET expires=0 WHERE token=?', (token,))
        self.assertEqual(self.run_action(token=token)['status'], 'BLOCKED')
        other = create_guarded_order(self.store, self.gateway)['local_order_id']
        other_token = approve_capture(self.store, other, '1.00', 'USD')
        self.assertEqual(self.run_action(token=other_token)['status'], 'BLOCKED')
        self.assertEqual(self.gateway.capture_calls, 0)

    def test_conflicting_workers_are_blocked_across_connections(self):
        second = Store(self.path)
        try:
            with _claim(second, self.local):
                self.assertEqual(self.run_action(token=self.approve())['status'], 'BLOCKED')
            self.assertEqual(self.gateway.capture_calls, 0)
        finally:
            second.db.close()

    def test_stale_crash_claim_is_not_automatically_reclaimed(self):
        with self.store.db:
            self.store.db.execute('INSERT INTO recovery_claims VALUES (?,?)', (self.local, 'crashed-worker'))
        self.assertEqual(self.run_action(token=self.approve())['status'], 'BLOCKED')

    def test_forged_evidence_and_stale_proposals_are_blocked(self):
        for stale in (False, True):
            session, decision = self.investigate()
            if stale:
                for observation in session._bundle['observations']:
                    observation['observed_at'] = '2000-01-01T00:00:00Z'
            else:
                decision['evidence_ids'] = ['made-up']
            result = execute_recovery(self.store, self.gateway, session, decision, approval_token=self.approve())
            self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(self.gateway.capture_calls, 0)

    def test_provider_mismatch_and_existing_pending_capture_block_capture(self):
        original = deepcopy(self.gateway.orders[self.remote])
        for field in ('identity', 'amount', 'pending'):
            remote = deepcopy(original)
            unit = remote['purchase_units'][0]
            if field == 'identity': unit['custom_id'] = 'other'
            elif field == 'amount': unit['amount']['value'] = '2.00'
            else: unit['payments'] = {'captures': [{'id': 'cap-pending', 'status': 'PENDING'}]}
            self.gateway.orders[self.remote] = remote
            self.assertEqual(self.run_action(token=self.approve())['status'], 'BLOCKED')
        self.assertEqual(self.gateway.capture_calls, 0)

    def test_journal_evidence_does_not_expose_request_keys_or_fault_names(self):
        session, _ = self.investigate()
        bundle = session.bundle()
        self.assertEqual(bundle['observations'][2]['data']['events'][0]['event'], 'CAPTURE_NOT_SENT')
        self.assertNotIn(self.store.order(self.local)['capture_key'], json.dumps(bundle))
        self.run_action(token=self.approve(), fault='lost-confirmation')
        session, _ = self.investigate()
        self.assertEqual(session.bundle()['observations'][2]['data']['events'], [])
        schema = json.loads((Path(__file__).parent / 'contracts/incident-v1.schema.json').read_text())
        Draft202012Validator(schema).validate(bundle)

    def test_legacy_attempt_never_authorizes_new_guarded_capture(self):
        capture(self.store, self.gateway, self.local, 'lost-confirmation')
        self.store.state(self.local, 'BLOCKED')
        session, _ = self.investigate()
        self.assertEqual(session.bundle()['observations'][2]['data']['events'], [])
        self.assertEqual(self.run_action(token=self.approve())['status'], 'BLOCKED')
        self.assertEqual(self.gateway.capture_calls, 1)

    def test_escalation_performs_no_payment_or_fulfillment_mutation(self):
        before = list(self.store.db.iterdump())
        self.assertEqual(self.run_action('escalate')['status'], 'NOT_EXECUTED')
        self.assertEqual(before, list(self.store.db.iterdump()))

    def test_request_key_and_uncertainty_are_persisted_before_network(self):
        expected = self.store.order(self.local)['capture_key']
        original = self.gateway.capture
        def checked(order_id, request_id):
            second = Store(self.path)
            try:
                row = second.db.execute('SELECT * FROM capture_journal WHERE order_id=?', (self.local,)).fetchone()
                self.assertEqual(row['state'], 'POSSIBLY_SENT')
                self.assertEqual(request_id, expected)
            finally:
                second.db.close()
            return original(order_id, request_id)
        with patch.object(self.gateway, 'capture', side_effect=checked):
            self.assertEqual(self.run_action(token=self.approve())['status'], 'SUCCEEDED')


if __name__ == '__main__':
    unittest.main()
