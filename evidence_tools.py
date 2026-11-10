"""Read-only diagnostic boundary for contract v1; never authorizes recovery."""
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
import re
import sqlite3
import uuid

from incidentlab import LabError

# str + Enum preserves Python 3.10 compatibility. Emit .value at JSON boundaries.
class ToolName(str, Enum):
    GET_LOCAL_ORDER = "get_local_order"
    GET_PAYPAL_ORDER = "get_paypal_order"
    GET_APPLICATION_EVENTS = "get_application_events"


class LocalOrderState(str, Enum):
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    PAID = "PAID"


class ProviderOrderState(str, Enum):
    CREATED = "CREATED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"
    PAYER_ACTION_REQUIRED = "PAYER_ACTION_REQUIRED"
    UNKNOWN = "UNKNOWN"


class CaptureState(str, Enum):
    COMPLETED = "COMPLETED"
    PENDING = "PENDING"
    DECLINED = "DECLINED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    UNKNOWN = "UNKNOWN"


# Keep the existing public constants available to current callers.
TOOLS = tuple(tool.value for tool in ToolName)
ORDER_STATES = frozenset(state.value for state in ProviderOrderState)
CAPTURE_STATES = frozenset(state.value for state in CaptureState)


def text(value):
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError("Invalid field")
    return value


def money(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid amount")
    amount = text(value.get("value"))
    if not re.fullmatch(r"\d+\.\d{2}", amount) or value.get("currency_code") != "USD":
        raise ValueError("Unsupported amount")
    return {"currency": "USD", "amount": amount}


class EvidenceSession:
    """One local order per investigation. Callers receive copies of the transcript.

    Pass a provider exposing get(provider_id), not model-selected URLs. Provider
    exceptions are reduced to fixed messages. This class never calls capture.
    """

    def __init__(self, store, gateway, order_id, *, mode, incident_id=None):
        if mode not in {"offline", "sandbox"}:
            raise ValueError("mode must be offline or sandbox")
        self.store, self.gateway = store, gateway
        self.order_id = text(order_id)
        self._bundle = {
            "contract_version": "1.0", "mode": mode,
            "incident_id": text(incident_id or uuid.uuid4().hex),
            "order_id": order_id, "symptom": "Checkout could not be confirmed",
            "observations": [],
        }

    def bundle(self):
        return deepcopy(self._bundle)

    def call(self, tool, arguments):
        # Reject invalid requests before touching storage or the provider.
        try:
            tool = ToolName(tool).value
        except (ValueError, TypeError):
            raise ValueError("Unsupported diagnostic tool") from None
        if not isinstance(arguments, dict) or set(arguments) != {"order_id"} or arguments["order_id"] != self.order_id:
            raise ValueError("Tool arguments must reference this session's local order")
        observation = {"evidence_id": uuid.uuid4().hex, "tool": tool}
        try:
            order = self.store.order(self.order_id)
            data = getattr(self, "_" + tool)(order)
            observation.update(status="OK", data=data)
        except TimeoutError:
            observation.update(status="ERROR", error={"code": "TIMEOUT", "message": "Diagnostic source timed out; payment outcome is not established."})
        except (LabError, sqlite3.Error, OSError):
            observation.update(status="ERROR", error={"code": "UNAVAILABLE", "message": "Diagnostic source unavailable; payment outcome is not established."})
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            observation.update(status="ERROR", error={"code": "INVALID_RESPONSE", "message": "Diagnostic source returned unsupported or incomplete evidence."})
        observation["observed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._bundle["observations"].append(deepcopy(observation))
        return deepcopy(observation)

    def _get_local_order(self, order):
        state = LocalOrderState(order["status"])
        capture_id = order["capture_id"]
        if capture_id is not None:
            text(capture_id)
        return {
            "order_id": self.order_id, "provider_order_id": text(order["provider_id"]),
            "payment_state": "PAID" if state == LocalOrderState.PAID else "UNCONFIRMED",
            **money({"value": order["amount"], "currency_code": order["currency"]}),
            "capture_id": capture_id,
            "fulfillment_count": self.store.db.execute(
                "SELECT count(*) FROM fulfillment WHERE order_id=?", (self.order_id,)).fetchone()[0],
        }

    def _get_paypal_order(self, order):
        provider_id = text(order["provider_id"])
        remote = self.gateway.get(provider_id)
        # Preserve differing IDs and amounts as evidence; never silently replace
        # them with expected local values. Unsupported shapes become tool errors.
        remote_id = text(remote["id"])
        status = ProviderOrderState(remote["status"]).value
        units = remote["purchase_units"]
        if not isinstance(units, list) or len(units) != 1:
            raise ValueError("Unsupported provider state")
        unit = units[0]
        captures = unit.get("payments", {}).get("captures", [])
        if not isinstance(captures, list):
            raise ValueError("Invalid captures")
        normalized = []
        for item in captures:
            capture_status = CaptureState(item["status"]).value
            normalized.append({"capture_id": text(item["id"]), "status": capture_status, **money(item["amount"])})
        return {
            "provider_order_id": remote_id, "status": status,
            "purchase_unit": {"provider_order_id": remote_id, "custom_id": text(unit["custom_id"]), **money(unit["amount"])},
            "captures": normalized,
        }

    def _get_application_events(self, order):
        # Legacy logs are incomplete. Only a matching guarded journal may assert
        # non-submission; a pre-network intent never establishes actual dispatch.
        exists = self.store.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='capture_journal'").fetchone()
        events = []
        if exists:
            journal = self.store.db.execute(
                "SELECT * FROM capture_journal WHERE order_id=?", (self.order_id,)).fetchone()
            started = self.store.db.execute(
                "SELECT 1 FROM events WHERE order_id=? AND kind='capture_started' LIMIT 1",
                (self.order_id,)).fetchone()
            matches = journal and all(journal[key] == order[key] for key in ('provider_id', 'amount', 'currency'))
            if matches and journal['state'] == 'UNSENT' and not started and order['status'] in {'AWAITING_APPROVAL', 'BLOCKED'}:
                events.append({'event': 'CAPTURE_NOT_SENT', 'message': 'Matching durable capture journal is UNSENT with no capture_started record.'})
        # This journal is not a complete historical application log.
        return {"coverage": "PARTIAL", "events": events}
