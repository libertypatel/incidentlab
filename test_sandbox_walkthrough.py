"""Exercise the walkthrough offline, including interrupted and repeated capture."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from incidentlab import Store
from guarded_recovery import create_guarded_order
from test_guarded_recovery import GuardedFake
from sandbox_walkthrough import run_step


class WalkthroughTests(unittest.TestCase):
    def test_lost_confirmation_then_read_only_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(StringIO()):
            path = Path(folder) / 'test.sqlite3'
            store, gateway = Store(path), GuardedFake()
            try:
                created = create_guarded_order(store, gateway)
                oid = created['local_order_id']
                gateway.approve(created['paypal_order_id'])
                with patch('builtins.input', return_value='no'):
                    self.assertEqual(run_step('lose-confirmation', store, gateway, path, oid), 1)
                self.assertEqual(gateway.capture_calls, 0)
                with patch('builtins.input', return_value='CAPTURE ' + oid):
                    self.assertEqual(run_step('lose-confirmation', store, gateway, path, oid), 0)
                self.assertEqual(store.order(oid)['status'], 'UNKNOWN')
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM fulfillment').fetchone()[0], 0)
                self.assertEqual(run_step('lose-confirmation', store, gateway, path, oid), 1)
                with patch.object(gateway, 'capture', side_effect=AssertionError('Capture forbidden')):
                    self.assertEqual(run_step('reconcile', store, gateway, path, oid), 0)
                    self.assertEqual(run_step('reconcile', store, gateway, path, oid), 0)
                self.assertEqual(gateway.capture_calls, 1)
                self.assertEqual(store.order(oid)['status'], 'PAID')
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM fulfillment').fetchone()[0], 1)
            finally:
                store.db.close()
