"""Offline behavior tests. These do not establish PayPal sandbox compatibility."""
from copy import deepcopy
import unittest
from incidentlab import Store, LabError, new_order, capture, reconcile, verify


class FakePayPal:
    def __init__(self):
        self.orders = {}
        self.capture_calls = 0
        self.lose_transport_response = False

    def create(self, local_id, request_id):
        order_id = f"SANDBOX-FAKE-{len(self.orders) + 1}"
        result = {"id": order_id, "status": "CREATED", "purchase_units": [{"custom_id": local_id}]}
        self.orders[order_id] = result
        return deepcopy(result)

    def approve(self, order_id):
        self.orders[order_id]["status"] = "APPROVED"

    def get(self, order_id):
        return deepcopy(self.orders[order_id])

    def capture(self, order_id, request_id):
        self.capture_calls += 1
        row = self.orders[order_id]
        row["status"] = "COMPLETED"
        row["purchase_units"][0]["payments"] = {"captures": [{
            "id": f"CAP-{order_id}", "status": "COMPLETED",
            "amount": {"currency_code": "USD", "value": "1.00"}}]}
        if self.lose_transport_response:
            raise LabError("Simulated timeout after provider committed payment")
        return deepcopy(row)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.gateway = FakePayPal()
        order = new_order(self.store, self.gateway)
        self.local = order["local_order_id"]
        self.remote = order["paypal_order_id"]
        self.gateway.approve(self.remote)

    def tearDown(self):
        self.store.db.close()

    def lose_confirmation(self):
        return capture(self.store, self.gateway, self.local, "lost-confirmation")

    def test_lost_confirmation_is_recovered_without_second_capture(self):
        self.lose_confirmation()
        self.assertEqual(self.store.order(self.local)["status"], "UNKNOWN")
        self.assertEqual(verify(self.store, self.gateway, self.local)["result"], "NOT_VERIFIED")
        result = reconcile(self.store, self.gateway, self.local)
        self.assertEqual(result["result"], "VERIFIED")
        self.assertEqual(self.gateway.capture_calls, 1)

    def test_repeated_recovery_fulfills_once(self):
        self.lose_confirmation()
        for _ in range(3):
            result = reconcile(self.store, self.gateway, self.local)
        self.assertEqual(result["simulated_fulfillment_count"], 1)
        self.assertEqual(self.gateway.capture_calls, 1)

    def test_similar_customer_errors_have_different_provider_states(self):
        blocked = capture(self.store, self.gateway, self.local, "before-submit")
        self.assertEqual(self.gateway.capture_calls, 0)
        self.assertEqual(reconcile(self.store, self.gateway, self.local)["result"], "NOT_VERIFIED")
        lost = self.lose_confirmation()
        self.assertEqual(blocked["customer_view"], lost["customer_view"])
        self.assertEqual(self.gateway.get(self.remote)["status"], "COMPLETED")

    def test_configuration_failure_can_be_cleared_by_explicit_operator_capture(self):
        capture(self.store, self.gateway, self.local, "before-submit")
        self.assertEqual(capture(self.store, self.gateway, self.local)["result"], "VERIFIED")

    def test_pending_capture_does_not_fulfill(self):
        self.lose_confirmation()
        self.gateway.orders[self.remote]["purchase_units"][0]["payments"]["captures"][0]["status"] = "PENDING"
        self.assertEqual(reconcile(self.store, self.gateway, self.local)["result"], "NOT_VERIFIED")
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM fulfillment").fetchone()[0], 0)

    def test_wrong_amount_and_currency_are_rejected(self):
        self.lose_confirmation()
        amount = self.gateway.orders[self.remote]["purchase_units"][0]["payments"]["captures"][0]["amount"]
        for value, currency in [("2.00", "USD"), ("1.00", "EUR")]:
            amount.update(value=value, currency_code=currency)
            with self.assertRaises(LabError):
                reconcile(self.store, self.gateway, self.local)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM fulfillment").fetchone()[0], 0)

    def test_wrong_local_order_identity_rejected(self):
        self.lose_confirmation()
        self.gateway.orders[self.remote]["purchase_units"][0]["custom_id"] = "another-order"
        with self.assertRaises(LabError):
            reconcile(self.store, self.gateway, self.local)

    def test_approval_is_not_payment(self):
        self.assertEqual(reconcile(self.store, self.gateway, self.local)["result"], "NOT_VERIFIED")

    def test_unknown_outcome_blocks_blind_capture_retry(self):
        self.lose_confirmation()
        with self.assertRaises(LabError):
            capture(self.store, self.gateway, self.local)
        self.assertEqual(self.gateway.capture_calls, 1)

    def test_transport_timeout_can_be_reconciled(self):
        self.gateway.lose_transport_response = True
        with self.assertRaises(LabError):
            capture(self.store, self.gateway, self.local)
        self.assertEqual(reconcile(self.store, self.gateway, self.local)["result"], "VERIFIED")
        self.assertEqual(self.gateway.capture_calls, 1)

    def test_verifier_detects_missing_fulfillment(self):
        capture(self.store, self.gateway, self.local)
        self.store.db.execute("DELETE FROM fulfillment")
        self.store.db.commit()
        self.assertEqual(verify(self.store, self.gateway, self.local)["result"], "NOT_VERIFIED")


if __name__ == "__main__":
    unittest.main()
