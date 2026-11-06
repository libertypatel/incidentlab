"""Validate synthetic team examples; makes no network or payment requests."""
import json
from pathlib import Path
import sys

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    raise SystemExit("Install jsonschema in your virtual environment; see contracts/README.md.")


def main():
    root = Path(__file__).resolve().parent
    schema = json.loads((root / "incident-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    paths = sorted(p for p in root.glob("*.json") if p.name != "incident-v1.schema.json")
    for path in paths:
        data = json.loads(path.read_text())
        validator.validate(data)
        bundle = data.get("evidence", data)
        observations = bundle.get("observations", [])
        ids = [item["evidence_id"] for item in observations]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate evidence ID in {path.name}")
        if "decision" in data:
            decision, execution = data["decision"], data["execution"]
            if not set(decision["evidence_ids"]) <= set(ids):
                raise ValueError("Decision cites nonexistent evidence")
            if decision["order_id"] != bundle["order_id"]:
                raise ValueError("Decision order differs from evidence order")
            if any(execution[key] != decision[key] for key in ("decision_id", "action")):
                raise ValueError("Execution differs from proposed decision")
            sequence = [item["sequence"] for item in data["timeline"]]
            if sequence != sorted(set(sequence)):
                raise ValueError("Timeline sequence must strictly increase")
            for item in data["timeline"]:
                if not set(item["evidence_ids"]) <= set(ids):
                    raise ValueError("Timeline cites nonexistent evidence")
            verification = data["verification"]
            if verification["status"] == "VERIFIED":
                names = {check["name"] for check in verification["checks"]}
                expected = {"provider_payment_completed", "order_identity_matches",
                            "amount_currency_match", "local_state_matches", "single_fulfillment"}
                if names != expected or len(verification["checks"]) != len(expected):
                    raise ValueError("VERIFIED requires each verification check once")
                if (not verification["completed_capture_id"]
                    or verification["local_payment_state"] != "PAID"
                    or verification["fulfillment_count"] != 1
                    or any(check["status"] != "PASS" for check in verification["checks"])):
                    raise ValueError("VERIFIED contradicts verification fields")
        print(f"PASS: {path.name}")
    print(f"Validated {len(paths)} synthetic examples. No payment requests were made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
