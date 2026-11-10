"""Fake-provider operator approval and independent demo verification."""
from pathlib import Path
import tempfile
import unittest
from offline_demo import Demo


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
