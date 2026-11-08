"""Workflow boundaries and truthful report outcomes using a fake provider."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from incidentlab import Store, LabError
from guarded_recovery import create_guarded_order, approve_capture, execute_recovery
from demo_guarded_recovery import propose
from demo_run_integration import manual_investigator
from test_guarded_recovery import GuardedFake
from run_integration import run_incident, RunUnavailable


class RunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'lab.sqlite3'
        self.store, self.gateway = Store(self.path), GuardedFake()
        created = create_guarded_order(self.store, self.gateway)
        self.local, self.remote = created['local_order_id'], created['paypal_order_id']
        self.gateway.approve(self.remote)
        self.approval = Mock(side_effect=lambda oid, amount, currency:
                             approve_capture(self.store, oid, amount, currency))

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def run_report(self, **options):
        defaults = dict(mode='offline', controller='manual', investigate=manual_investigator,
                        request_approval=self.approval)
        defaults.update(options)
        return run_incident(self.store, self.gateway, self.path, self.local, **defaults)

    def test_capture_keeps_before_evidence_and_verifies_afterward(self):
        report = self.run_report()
        self.assertEqual(report['controller'], 'manual')
        self.assertEqual(report['execution']['status'], 'SUCCEEDED')
        self.assertEqual(report['verification']['status'], 'VERIFIED')
        before = report['evidence']['observations']
        self.assertEqual(before[0]['data']['payment_state'], 'UNCONFIRMED')
        self.assertEqual(before[1]['data']['status'], 'APPROVED')
        self.assertEqual(before[1]['data']['captures'], [])
        self.assertEqual(self.gateway.capture_calls, 1)
        self.approval.assert_called_once_with(self.local, '1.00', 'USD')
        self.assertNotIn('request_key', json.dumps(report))
        timeline = report['timeline']
        self.assertEqual([row['sequence'] for row in timeline], list(range(1, len(timeline) + 1)))

    def test_lost_confirmation_reconciles_without_new_approval_or_capture(self):
        session, decision = propose(self.store, self.gateway, self.local, 'capture_approved_order')
        token = approve_capture(self.store, self.local, '1.00', 'USD')
        execute_recovery(self.store, self.gateway, session, decision,
                         approval_token=token, fault='lost-confirmation')
        report = self.run_report()
        self.assertEqual(report['decision']['action'], 'reconcile_order')
        self.assertEqual(report['verification']['status'], 'VERIFIED')
        self.assertEqual(self.gateway.capture_calls, 1)
        self.approval.assert_not_called()

    def test_missing_operator_approval_is_blocked(self):
        report = self.run_report(request_approval=None)
        self.assertEqual(report['execution']['status'], 'BLOCKED')
        self.assertEqual(report['verification']['status'], 'NOT_VERIFIED')
        self.assertEqual(self.gateway.capture_calls, 0)

    def test_invalid_proposals_stop_before_approval_or_execution(self):
        for change in ({'evidence_ids': ['invented']}, {'order_id': 'other'}, {'action': 'refund'}):
            def invalid(context, call_tool):
                decision = manual_investigator(context, call_tool)
                decision.update(change)
                return decision
            with self.subTest(change=change), self.assertRaises(RunUnavailable):
                self.run_report(investigate=invalid)
        self.approval.assert_not_called()
        self.assertEqual(self.gateway.capture_calls, 0)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM recovery_runs').fetchone()[0], 0)

    def test_caught_budget_violation_still_prevents_execution(self):
        def exceeded(context, call_tool):
            decision = manual_investigator(context, call_tool)
            try:
                call_tool('get_local_order', {'order_id': context['order_id']})
            except RunUnavailable:
                pass
            return decision
        with self.assertRaises(RunUnavailable):
            self.run_report(investigate=exceeded, max_tool_calls=3)
        self.assertEqual(self.gateway.capture_calls, 0)
        self.approval.assert_not_called()

    def test_provider_outage_escalates_and_verifies_inconclusive(self):
        with patch.object(self.gateway, 'get', side_effect=LabError('private provider detail')):
            report = self.run_report()
        self.assertEqual(report['decision']['action'], 'escalate')
        self.assertEqual(report['execution']['status'], 'NOT_EXECUTED')
        self.assertEqual(report['verification']['status'], 'INCONCLUSIVE')
        self.assertNotIn('private provider detail', json.dumps(report))
        self.assertEqual(self.gateway.capture_calls, 0)
        self.approval.assert_not_called()

    def test_verifier_outage_does_not_turn_execution_into_verified(self):
        original_get = self.gateway.get
        reads = 0
        def get(remote_id):
            nonlocal reads
            reads += 1
            # Evidence GET, pre-capture GET, finalize GET, independent GET.
            if reads == 4:
                raise LabError('offline outage')
            return original_get(remote_id)
        with patch.object(self.gateway, 'get', side_effect=get):
            report = self.run_report()
        self.assertEqual(report['execution']['status'], 'SUCCEEDED')
        self.assertEqual(report['verification']['status'], 'INCONCLUSIVE')
        self.assertEqual(self.gateway.capture_calls, 1)

    def test_wrong_database_is_rejected_before_investigation(self):
        investigator = Mock()
        with self.assertRaises(RunUnavailable):
            run_incident(self.store, self.gateway, self.path.with_name('other.sqlite3'), self.local,
                         mode='offline', controller='manual', investigate=investigator)
        investigator.assert_not_called()

    def test_controller_exception_is_sanitized_without_mutation(self):
        with self.assertRaisesRegex(RunUnavailable, '^Investigation failed validation') as caught:
            self.run_report(investigate=Mock(side_effect=RuntimeError('SECRET')))
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertEqual(self.gateway.capture_calls, 0)

    def test_returned_tool_result_cannot_rewrite_transcript(self):
        def tamper(context, call_tool):
            row = call_tool('get_local_order', {'order_id': context['order_id']})
            row['data']['payment_state'] = 'PAID'
            return {'decision_id': 'manual', 'order_id': context['order_id'], 'action': 'escalate',
                    'summary': 'Manual escalation.', 'evidence_ids': [row['evidence_id']]}
        report = self.run_report(investigate=tamper)
        self.assertEqual(report['evidence']['observations'][0]['data']['payment_state'], 'UNCONFIRMED')
        self.assertEqual(report['execution']['status'], 'NOT_EXECUTED')


if __name__ == '__main__':
    unittest.main()
