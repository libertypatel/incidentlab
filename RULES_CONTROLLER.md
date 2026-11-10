# Rules baseline controller

`rules_controller.rules_investigator(context, call_tool)` is the deterministic
baseline that the AI investigator is evaluated against. It uses the same
interface, the same three diagnostic tools, the same tool budget, and the same
ability to escalate. Run it with `controller="rules"`.

```python
from rules_controller import rules_investigator
report = run_incident(store, gateway, db_path, order_id, mode="offline",
                      controller="rules", investigate=rules_investigator,
                      request_approval=operator_approval)
```

## Run

```sh
python3 -m unittest test_rules_controller -v
python3 -m unittest -v
```

All tests use synthetic evidence and a fake provider. No AI or PayPal requests occur.

## Decision table

The controller always makes three calls (local order, PayPal order, application
events), so it needs `max_tool_calls >= 3`. Anything not listed escalates.

| Action | Required evidence (all must hold) |
| --- | --- |
| `reconcile_order` | All tools OK; local `UNCONFIRMED`, zero fulfillments; IDs, `custom_id`, amount, and currency match; PayPal `COMPLETED` with exactly one `COMPLETED` capture matching amount/currency; local capture reference absent or equal |
| `capture_approved_order` | All tools OK; local `UNCONFIRMED`, zero fulfillments, no capture reference; identity/amount/currency match; PayPal `APPROVED` with no captures; a `CAPTURE_NOT_SENT` event |
| `escalate` | Any tool error, malformed data, already paid, local inconsistency, identity/amount mismatch, multiple/pending/refunded/declined captures, unsupported order status, or no evidence that capture was never sent |

Summaries are fixed templates, so no provider or log text is copied into the
report. Evidence IDs cite the observations the rule relied on. The proposal is not
authorization: the guarded executor rechecks state, capture still needs operator
approval, and the independent verifier decides the outcome.

## Limits

These rules were written with knowledge of the two supported scenarios. They are a
baseline, not a held-out result. `investigator.branching_rules` is this controller,
so `evaluation.py` and the offline demo use it as the rules baseline.
