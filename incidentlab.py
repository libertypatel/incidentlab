"""IncidentLab milestone 1. Python standard library only; sandbox only."""
import argparse
import base64
import json
import os
from pathlib import Path
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation


class LabError(Exception):
    pass


class PayPal:
    BASE = "https://api-m.sandbox.paypal.com"

    def __init__(self):
        client = os.environ.get("PAYPAL_CLIENT_ID", "")
        secret = os.environ.get("PAYPAL_CLIENT_SECRET", "")
        if not client or not secret:
            raise LabError("Set sandbox PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET locally. See README.md.")
        basic = base64.b64encode(f"{client}:{secret}".encode()).decode()
        result = self._http("POST", "/v1/oauth2/token", b"grant_type=client_credentials", {
            "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
        self.token = result["access_token"]

    def _http(self, method, path, body=None, headers=None):
        # No configurable host: credentials can only be sent to PayPal sandbox.
        request = urllib.request.Request(self.BASE + path, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                error = json.loads(exc.read())
            except (ValueError, OSError):
                error = {}
            # Do not print response bodies, credentials, or payer details.
            raise LabError(f"PayPal HTTP {exc.code}; {error.get('name', 'API_ERROR')}; "
                           f"debug_id={error.get('debug_id', 'unavailable')}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise LabError("PayPal connection failed or timed out. Outcome may be unknown; inspect/reconcile before retrying.") from None

    def request(self, method, path, body=None, request_id=None):
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                   "Prefer": "return=representation"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        return self._http(method, path, None if body is None else json.dumps(body).encode(), headers)

    def create(self, local_id, request_id):
        return self.request("POST", "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{"reference_id": local_id, "custom_id": local_id,
                                "amount": {"currency_code": "USD", "value": "1.00"}}],
            "payment_source": {"paypal": {"experience_context": {
                "brand_name": "IncidentLab Sandbox", "shipping_preference": "NO_SHIPPING",
                "user_action": "PAY_NOW", "return_url": "http://localhost:8765/approved",
                "cancel_url": "http://localhost:8765/cancelled"}}}
        }, request_id)

    def get(self, order_id):
        return self.request("GET", "/v2/checkout/orders/" + urllib.parse.quote(order_id, safe=""))

    def capture(self, order_id, request_id):
        return self.request("POST", "/v2/checkout/orders/" + urllib.parse.quote(order_id, safe="") + "/capture", {}, request_id)


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY, provider_id TEXT UNIQUE, create_key TEXT NOT NULL,
            capture_key TEXT NOT NULL, status TEXT NOT NULL, capture_id TEXT,
            amount TEXT NOT NULL DEFAULT '1.00', currency TEXT NOT NULL DEFAULT 'USD');
          CREATE TABLE IF NOT EXISTS fulfillment (
            order_id TEXT PRIMARY KEY REFERENCES orders(id), capture_id TEXT UNIQUE NOT NULL);
          CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY, at TEXT DEFAULT CURRENT_TIMESTAMP,
            order_id TEXT, kind TEXT, detail TEXT);
        """)

    def event(self, local_id, kind, detail):
        self.db.execute("INSERT INTO events(order_id,kind,detail) VALUES (?,?,?)", (local_id, kind, detail))
        self.db.commit()

    def order(self, local_id):
        row = self.db.execute("SELECT * FROM orders WHERE id=?", (local_id,)).fetchone()
        if row is None:
            raise LabError("Unknown local order ID.")
        return dict(row)

    def state(self, local_id, status):
        self.db.execute("UPDATE orders SET status=? WHERE id=?", (status, local_id))
        self.db.commit()


def new_order(store, gateway):
    local_id = uuid.uuid4().hex
    create_key, capture_key = str(uuid.uuid4()), str(uuid.uuid4())
    store.db.execute("INSERT INTO orders(id,create_key,capture_key,status) VALUES (?,?,?,?)",
                     (local_id, create_key, capture_key, "CREATING"))
    store.db.commit()
    # The local intent and idempotency keys exist before any network mutation.
    try:
        result = gateway.create(local_id, create_key)
    except LabError:
        store.state(local_id, "CREATE_UNKNOWN")
        raise LabError(f"Create outcome unknown for local order {local_id}. Do not automatically create a replacement.") from None
    store.db.execute("UPDATE orders SET provider_id=?, status='AWAITING_APPROVAL' WHERE id=?", (result["id"], local_id))
    store.db.commit()
    store.event(local_id, "order_created", "Sandbox order created; buyer approval required.")
    approval = next((link["href"] for link in result.get("links", [])
                     if link.get("rel") in {"approve", "payer-action"}), None)
    return {"local_order_id": local_id, "paypal_order_id": result["id"], "approval_url": approval}


def capture(store, gateway, local_id, fault="none"):
    order = store.order(local_id)
    if not order["provider_id"]:
        raise LabError("Order creation incomplete; no provider ID available.")
    if order["status"] == "UNKNOWN":
        raise LabError("Capture outcome is unknown. Run reconcile before considering another capture.")
    if order["status"] == "PAID":
        return {"result": "ALREADY_PAID", "local_order_id": local_id}
    remote = gateway.get(order["provider_id"])
    if remote.get("status") == "COMPLETED":
        return reconcile(store, gateway, local_id)
    if remote.get("status") != "APPROVED":
        raise LabError("Buyer approval is required before capture; open the approval URL first.")
    if fault == "before-submit":
        store.state(local_id, "BLOCKED")
        store.event(local_id, "capture_blocked", "Injected local configuration failure; no capture request sent.")
        return {"customer_view": "Checkout could not be confirmed", "local_status": "BLOCKED"}
    store.state(local_id, "UNKNOWN")
    store.event(local_id, "capture_started", "Outcome unknown until confirmed; stable capture request ID persisted.")
    gateway.capture(order["provider_id"], order["capture_key"])
    if fault == "lost-confirmation":
        store.event(local_id, "confirmation_lost", "Injected failure after response: local confirmation write skipped.")
        return {"customer_view": "Checkout could not be confirmed", "local_status": "UNKNOWN"}
    # Recovery and verification read provider state, rather than trusting capture success alone.
    return reconcile(store, gateway, local_id)


def payment_evidence(order, remote):
    if remote.get("id") != order["provider_id"]:
        raise LabError("Provider order ID mismatch; refusing recovery.")
    units = remote.get("purchase_units", [])
    if len(units) != 1 or units[0].get("custom_id") != order["id"]:
        raise LabError("Purchase-unit identity mismatch; refusing recovery.")
    captures = units[0].get("payments", {}).get("captures", [])
    if remote.get("status") != "COMPLETED" or len(captures) != 1:
        return None
    item = captures[0]
    if item.get("status") != "COMPLETED":
        return None
    try:
        correct_amount = Decimal(item["amount"]["value"]) == Decimal(order["amount"])
        correct_currency = item["amount"]["currency_code"] == order["currency"]
    except (KeyError, InvalidOperation, TypeError):
        raise LabError("Missing or invalid capture amount; refusing recovery.") from None
    if not correct_amount or not correct_currency or not item.get("id"):
        raise LabError("Capture amount/currency/identity mismatch; refusing recovery.")
    return item["id"]


def reconcile(store, gateway, local_id):
    order = store.order(local_id)
    if not order["provider_id"]:
        raise LabError("No provider order ID to reconcile.")
    # This operation never calls capture and cannot charge a buyer.
    remote = gateway.get(order["provider_id"])
    capture_id = payment_evidence(order, remote)
    store.event(local_id, "provider_checked", f"provider_status={remote.get('status', 'UNKNOWN')}; completed_capture={bool(capture_id)}")
    if capture_id is None:
        return {"result": "NOT_VERIFIED", "provider_status": remote.get("status"),
                "next_step": "Inspect evidence; do not fulfill or blindly retry."}
    with store.db:
        previous = store.db.execute("SELECT capture_id FROM fulfillment WHERE order_id=?", (local_id,)).fetchone()
        if previous and previous["capture_id"] != capture_id:
            raise LabError("Conflicting fulfillment evidence; refusing recovery.")
        store.db.execute("INSERT OR IGNORE INTO fulfillment(order_id,capture_id) VALUES (?,?)", (local_id, capture_id))
        store.db.execute("UPDATE orders SET status='PAID', capture_id=? WHERE id=?", (capture_id, local_id))
    store.event(local_id, "reconciled", "Local order and one simulated fulfillment record committed atomically.")
    return verify(store, gateway, local_id)


def verify(store, gateway, local_id):
    # Separate read-only verification: fresh API read + local DB checks; no repair calls.
    order = store.order(local_id)
    capture_id = payment_evidence(order, gateway.get(order["provider_id"]))
    rows = store.db.execute("SELECT capture_id FROM fulfillment WHERE order_id=?", (local_id,)).fetchall()
    passed = bool(capture_id and order["status"] == "PAID" and order["capture_id"] == capture_id
                  and len(rows) == 1 and rows[0]["capture_id"] == capture_id)
    return {"result": "VERIFIED" if passed else "NOT_VERIFIED", "local_order_id": local_id,
            "local_status": order["status"], "completed_capture_id": capture_id,
            "simulated_fulfillment_count": len(rows)}


def load_env():
    path = Path(".env")
    if path.exists():
        for raw in path.read_text(encoding='utf-8').splitlines():
            raw = raw.strip()
            if raw and not raw.startswith("#") and "=" in raw:
                key, value = raw.split("=", 1)
                if key in {"PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
                           "INCIDENTLAB_LLM_URL", "INCIDENTLAB_MODEL", "INCIDENTLAB_LLM_KEY"}:
                    os.environ.setdefault(key, value.strip().strip("\"'"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="incidentlab.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create")
    for name in ("capture", "reconcile", "verify", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("order_id", help="Local order ID printed by create")
        if name == "capture":
            command.add_argument("--fault", choices=["none", "before-submit", "lost-confirmation"], default="none")
    args = parser.parse_args()
    load_env()
    store = Store(args.db)
    try:
        if args.command == "inspect":
            result = {"order": store.order(args.order_id), "events": [dict(row) for row in store.db.execute(
                "SELECT seq,at,kind,detail FROM events WHERE order_id=? ORDER BY seq", (args.order_id,))]}
        else:
            gateway = PayPal()
            if args.command == "create":
                result = new_order(store, gateway)
            elif args.command == "capture":
                result = capture(store, gateway, args.order_id, args.fault)
            elif args.command == "reconcile":
                result = reconcile(store, gateway, args.order_id)
            else:
                result = verify(store, gateway, args.order_id)
        print(json.dumps(result, indent=2))
    except LabError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        store.db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
