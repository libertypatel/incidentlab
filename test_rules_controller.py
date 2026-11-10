"""Rules baseline: decision table and end-to-end runs with a fake provider."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from incidentlab import Store, LabError
from guarded_recovery import create_guarded_order, approve_capture, execute_recovery
from demo_guarded_recovery import propose
from test_guarded_recovery import GuardedFake
from run_integration import run_incident, RunUnavailable, _validator
from rules_controller import rules_investigator, decide, TOOL_ORDER

CONTRACTS = Path(__file__).parent / 'contracts'


def observations(name):
    rows = json.loads((CONTRACTS / name).read_text())['observations']
    return {row['tool']: row for row in rows}


class DecisionTableTests(unittest.TestCase):
    """Variations of the capture-blocked fixture (01) and lost-confirmation fixture (02)."""

    def setUp(self):
        self.blocked = observations('evidence-01.json')
        self.lost = observations('evidence-02.json')

    def decide(self, rows, edit=None):
        rows = deepcopy(rows)
        if edit:
            edit(rows)
        local, provider, events = (rows[tool] for tool in TOOL_ORDER)
        action, _, cited = decide('order_demo', local, provider, events)
        return action, [row['evidence_id'] for row in cited]

    def assertEscalates(self, rows, edit):
        self.assertEqual(self.decide(rows, edit)[0], 'escalate')

    def test_supported_patterns(self):
        self.assertEqual(self.decide(self.blocked), ('capture_approved_order', ['e1', 'e2', 'e3']))
        self.assertEqual(self.decide(self.lost), ('reconcile_order', ['e1', 'e2']))

    def test_reconcile_does_not_depend_on_application_events(self):
        def no_events(rows):
            rows['get_application_events']['data'] = {'coverage': 'UNAVAILABLE', 'events': []}
        self.assertEqual(self.decide(self.lost, no_events)[0], 'reconcile_order')

    def test_matching_local_capture_reference_still_reconciles(self):
        def recorded(rows):
            rows['get_local_order']['data']['capture_id'] = 'capture_demo'
        self.assertEqual(self.decide(self.lost, recorded)[0], 'reconcile_order')

    def test_tool_errors_escalate_and_cite_the_failure(self):
        for tool in TOOL_ORDER:
            for rows in (self.blocked, self.lost):
                def fail(rows, tool=tool):
                    row = rows[tool]
                    row.pop('data')
                    row.update(status='ERROR', error={'code': 'TIMEOUT', 'message': 'x'})
                with self.subTest(tool=tool):
                    action, cited = self.decide(rows, fail)
                    self.assertEqual(action, 'escalate')
                    self.assertEqual(cited, [rows[tool]['evidence_id']])

    def test_capture_blocked_variations_escalate(self):
        def local(**fields):
            return lambda rows: rows['get_local_order']['data'].update(fields)
        def remote(**fields):
            return lambda rows: rows['get_paypal_order']['data'].update(fields)
        def unit(**fields):
            return lambda rows: rows['get_paypal_order']['data']['purchase_unit'].update(fields)
        def no_journal(rows):
            rows['get_application_events']['data']['events'] = []
        cases = {
            'already paid': local(payment_state='PAID'),
            'corrupt local state': local(payment_state='SOMETHING'),
            'already fulfilled': local(fulfillment_count=1),
            'local capture without provider capture': local(capture_id='capture_x'),
            'custom_id mismatch': unit(custom_id='other_order'),
            'provider id mismatch': remote(provider_order_id='provider_other'),
            'unit provider id mismatch': unit(provider_order_id='provider_other'),
            'local provider id mismatch': local(provider_order_id='provider_other'),
            'amount mismatch': unit(amount='2.00'),
            'currency mismatch': unit(currency='EUR'),
            'not yet approved': remote(status='CREATED'),
            'payer action required': remote(status='PAYER_ACTION_REQUIRED'),
            'voided': remote(status='VOIDED'),
            'completed without capture': remote(status='COMPLETED'),
            'no CAPTURE_NOT_SENT evidence': no_journal,
            'malformed provider data': lambda rows: rows['get_paypal_order']['data'].pop('captures'),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                self.assertEscalates(self.blocked, edit)

    def test_lost_confirmation_variations_escalate(self):
        def capture(**fields):
            return lambda rows: rows['get_paypal_order']['data']['captures'][0].update(fields)
        def second_capture(rows):
            captures = rows['get_paypal_order']['data']['captures']
            captures.append(dict(captures[0], capture_id='capture_two'))
        cases = {
            'pending capture': capture(status='PENDING'),
            'refunded capture': capture(status='REFUNDED'),
            'partially refunded': capture(status='PARTIALLY_REFUNDED'),
            'declined capture': capture(status='DECLINED'),
            'capture amount mismatch': capture(amount='0.50'),
            'capture currency mismatch': capture(currency='EUR'),
            'multiple captures': second_capture,
            'order not completed': lambda rows: rows['get_paypal_order']['data'].update(status='APPROVED'),
            'different local capture': lambda rows: rows['get_local_order']['data'].update(capture_id='other'),
            'already fulfilled': lambda rows: rows['get_local_order']['data'].update(fulfillment_count=1),
            'order amount mismatch': lambda rows: rows['get_paypal_order']['data']['purchase_unit'].update(amount='2.00'),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                self.assertEscalates(self.lost, edit)

    def test_decisions_are_schema_valid_with_fixed_summaries(self):
        for rows in (self.blocked, self.lost):
            rows = deepcopy(rows)
            rows['get_paypal_order']['data']['status'] = '<script>alert(1)</script>'
            call = Mock(side_effect=lambda tool, args, rows=rows: rows[tool])
            decision = rules_investigator({'order_id': 'order_demo', 'incident_id': 'inc_demo'}, call)
            _validator('decision').validate(decision)
            self.assertEqual(decision['action'], 'escalate')
            self.assertNotIn('script', decision['summary'])
            self.assertEqual([c.args[0] for c in call.call_args_list], list(TOOL_ORDER))


class RulesRunTests(unittest.TestCase):
    """Full run_incident path: guarded executor plus independent verifier."""

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

    def run_rules(self, **options):
        settings = dict(mode='offline', controller='rules', investigate=rules_investigator,
                        request_approval=self.approval)
        settings.update(options)
        return run_incident(self.store, self.gateway, self.path, self.local, **settings)

    def lose_confirmation(self):
        session, decision = propose(self.store, self.gateway, self.local, 'capture_approved_order')
        token = approve_capture(self.store, self.local, '1.00', 'USD')
        execute_recovery(self.store, self.gateway, session, decision,
                         approval_token=token, fault='lost-confirmation')

    def assertEscalatedWithoutMutation(self, report, captures=0):
        self.assertEqual(report['decision']['action'], 'escalate')
        self.assertEqual(report['execution']['status'], 'NOT_EXECUTED')
        self.assertNotEqual(report['verification']['status'], 'VERIFIED')
        self.assertEqual(self.gateway.capture_calls, captures)
        self.approval.assert_not_called()

    def test_capture_blocked_recovers_and_verifies(self):
        self.store.state(self.local, 'BLOCKED')
        report = self.run_rules()
        self.assertEqual(report['controller'], 'rules')
        self.assertEqual(report['decision']['action'], 'capture_approved_order')
        self.assertEqual(report['execution']['status'], 'SUCCEEDED')
        self.assertEqual(report['verification']['status'], 'VERIFIED')
        self.assertEqual(self.gateway.capture_calls, 1)
        self.approval.assert_called_once_with(self.local, '1.00', 'USD')

    def test_lost_confirmation_reconciles_without_recapture(self):
        self.lose_confirmation()
        report = self.run_rules()
        self.assertEqual(report['decision']['action'], 'reconcile_order')
        self.assertEqual(report['verification']['status'], 'VERIFIED')
        self.assertEqual(self.gateway.capture_calls, 1)
        self.approval.assert_not_called()

    def test_second_run_after_recovery_escalates(self):
        self.store.state(self.local, 'BLOCKED')
        self.run_rules()
        self.approval.reset_mock()
        report = self.run_rules()
        self.assertEqual(report['decision']['action'], 'escalate')
        self.assertEqual(report['verification']['status'], 'VERIFIED')
        self.assertEqual(self.gateway.capture_calls, 1)
        self.approval.assert_not_called()

    def test_missing_dispatch_journal_escalates(self):
        self.store.db.execute('DELETE FROM capture_journal')
        self.store.db.commit()
        self.assertEscalatedWithoutMutation(self.run_rules())

    def test_provider_outage_escalates(self):
        with patch.object(self.gateway, 'get', side_effect=LabError('private detail')):
            report = self.run_rules()
        self.assertEscalatedWithoutMutation(report)
        self.assertNotIn('private detail', json.dumps(report))

    def test_amount_mismatch_escalates(self):
        self.gateway.orders[self.remote]['purchase_units'][0]['amount']['value'] = '2.00'
        self.assertEscalatedWithoutMutation(self.run_rules())

    def test_pending_or_refunded_capture_escalates(self):
        self.lose_confirmation()
        capture = self.gateway.orders[self.remote]['purchase_units'][0]['payments']['captures'][0]
        for status in ('PENDING', 'REFUNDED'):
            with self.subTest(status):
                capture['status'] = status
                self.assertEscalatedWithoutMutation(self.run_rules(), captures=1)

    def test_insufficient_budget_stops_before_execution(self):
        self.store.state(self.local, 'BLOCKED')
        with self.assertRaises(RunUnavailable):
            self.run_rules(max_tool_calls=2)
        self.assertEqual(self.gateway.capture_calls, 0)
        self.approval.assert_not_called()


if __name__ == '__main__':
    unittest.main()
