"""Fake-provider operator approval and independent demo verification."""
from pathlib import Path
import tempfile
import unittest
from offline_demo import Demo
from investigator import branching_rules
from run_integration import RunUnavailable


class OfflineDemoTests(unittest.TestCase):
    def test_interactive_demo_requires_capture_approval_and_preserves_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            demo = Demo(Path(folder))
            for card in demo.state():
                oid = card['order_id']
                if card['family'] == 'before-submit':
                    demo.execute(oid, False)
                    self.assertEqual(demo.orders[oid]['gateway'].capture_calls, 0)
                demo.execute(oid, card['family'] == 'before-submit')
            final = demo.state()
            self.assertTrue(all(c['verification']['status'] == 'VERIFIED' for c in final))
            self.assertTrue(all(c['capture_count'] == 1 for c in final))

    def test_ai_mode_separates_investigation_and_human_execution(self):
        # Scripted callback tests UI plumbing, not real-model performance.
        calls = []
        def scripted(context, call_tool):
            calls.append(context['order_id'])
            return branching_rules(context, call_tool)
        with tempfile.TemporaryDirectory() as folder:
            demo = Demo(Path(folder), investigator=scripted)
            for card in demo.state():
                self.assertIsNone(card['proposal'])
                self.assertEqual(card['controller'], 'agent')
                with self.assertRaises(ValueError):
                    demo.execute(card['order_id'], True)
            self.assertEqual(calls, [])
            for card in demo.state():
                oid = card['order_id']
                initial = card['capture_count']
                demo.investigate(oid)
                self.assertEqual(demo.orders[oid]['gateway'].capture_calls, initial)
                count = len(calls)
                demo.state()
                self.assertEqual(len(calls), count)
                demo.execute(oid, card['family'] == 'before-submit')
                self.assertEqual(len(calls), count + 1)
                with self.assertRaises(ValueError):
                    demo.execute(oid, True)
            self.assertTrue(all(c['verification']['status'] == 'VERIFIED' for c in demo.state()))
            self.assertTrue(all(c['capture_count'] == 1 for c in demo.state()))

    def test_ai_mode_cannot_capture_without_operator_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            demo = Demo(Path(folder), investigator=branching_rules)
            card = next(c for c in demo.state() if c['family'] == 'before-submit')
            demo.investigate(card['order_id'])
            demo.execute(card['order_id'], False)
            self.assertEqual(demo.orders[card['order_id']]['gateway'].capture_calls, 0)
            self.assertEqual(demo.orders[card['order_id']]['report']['execution']['status'], 'BLOCKED')

    def test_changed_ai_proposal_cannot_execute(self):
        count = 0
        def changed(context, call_tool):
            nonlocal count
            count += 1
            proposal = branching_rules(context, call_tool)
            if count > 1:
                proposal['action'] = 'escalate'
            return proposal
        with tempfile.TemporaryDirectory() as folder:
            demo = Demo(Path(folder), investigator=changed)
            card = next(c for c in demo.state() if c['family'] == 'before-submit')
            demo.investigate(card['order_id'])
            with self.assertRaises(RunUnavailable):
                demo.execute(card['order_id'], True)
            self.assertEqual(demo.orders[card['order_id']]['gateway'].capture_calls, 0)
