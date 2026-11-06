"""Deterministic offline walkthrough; no AI or PayPal network requests."""
import json
from incidentlab import Store, new_order, capture, reconcile, verify
from test_recovery import FakePayPal


def main():
    print("OFFLINE SIMULATION — fake payment provider; no AI; no real sandbox transaction.\n")
    for fault in ("before-submit", "lost-confirmation"):
        store, gateway = Store(":memory:"), FakePayPal()
        created = new_order(store, gateway)
        local = created["local_order_id"]
        gateway.approve(created["paypal_order_id"])
        print("SCENARIO:", fault)
        print("Customer:", json.dumps(capture(store, gateway, local, fault)))
        print("Verifier before recovery:", json.dumps(verify(store, gateway, local)))
        print("Read-only payment investigation:", json.dumps(reconcile(store, gateway, local)))
        if fault == "before-submit":
            print("Operator clears local fault and explicitly submits approved payment:")
            print(json.dumps(capture(store, gateway, local)))
        print("Repeated reconciliation:", json.dumps(reconcile(store, gateway, local)))
        print("Total provider capture calls:", gateway.capture_calls, "\n")
        store.db.close()


if __name__ == "__main__":
    main()
