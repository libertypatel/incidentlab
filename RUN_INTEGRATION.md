# Incident run integration

`run_integration.run_incident` connects diagnostic tools, one proposed action,
the guarded executor, and the independent verifier. It returns an
`incident_run` matching `contracts/incident-v1.schema.json`.

## Offline walkthrough

From the repository with its virtual environment active:

```sh
python3 demo_run_integration.py
python3 -m unittest -v
python3 contracts/validate_examples.py
```

The demo prints the paths of two synthetic JSON files in a temporary output
folder. Files remain there for the report developer to inspect. An optional
`--output-dir /tmp/incidentlab-reports` sets their destination. Do not commit
runtime reports. Both scenarios should show `SUCCEEDED`, `VERIFIED`, and one
provider capture each. The lost-confirmation scenario reconciles its existing
capture. All requests use a fake provider; the controller is explicitly manual.

## Investigator adapter

Call `run_incident(store, gateway, db_path, order_id, mode=..., controller=...,
investigate=..., request_approval=...)` from trusted application code.

- `investigate(context, call_tool)` returns a contract decision dictionary.
- Context contains the contract version, mode, incident ID, order ID, and fixed
  customer symptom. It contains no injected fault label or approval token.
- `call_tool(name, {"order_id": context["order_id"]})` exposes only the three
  diagnostic tools. Results are copies; changing them cannot edit the transcript.
- Six diagnostic calls are allowed by default (configurable from one to twelve).
  An invalid request or exceeded budget prevents execution even if caught by the
  callback. A valid tool result with status `ERROR` remains usable evidence.
- Decisions must match the schema, order, and evidence IDs in the trusted session.
  The executor separately checks evidence freshness and current payment state.
- Set `controller="agent"` only when the real AI adapter is installed and invoked;
  use `manual` or `rules` accurately. The demo is not an AI evaluation.

`request_approval(order_id, amount, currency)` belongs to the trusted operator
interface. After a human explicitly approves those details, it may call
`approve_capture` and return that token. Returning `None` or omitting the callback
leaves capture blocked. Never give the investigator this callback or token.
The demo's automatic approval is a simulation confined to its fake provider.

## Report adapter and limits

The returned report preserves evidence collected before execution. Timeline
entries distinguish detection, tool results, decision, execution, and independent
verification. A successful execution alone never means `VERIFIED`. Pass this
report to the teammate's renderer; escape all text when rendering HTML, including
model summaries. Do not accept a model-produced report as authoritative.

`RunUnavailable` means no complete report was returned. Investigation/approval
failures happen before recovery; post-execution failures explicitly say to inspect
before retrying because a payment may already have happened. Provider read errors
normally produce evidence `ERROR` or verification `INCONCLUSIVE` instead.

This is a synchronous application adapter, not a sandbox for arbitrary Python.
Callbacks are trusted code; their transport must enforce its own timeouts and
model limits. The tool-call budget does not impose a wall-clock deadline. The
supplied database must be the Store's actual file. Use the guarded path for all
new mutations; legacy CLI mutations are outside its coordination guarantees.
The mode label must match the supplied gateway. No sandbox PayPal validation,
HTML renderer, AI transport, or agent evaluation is added by these files.
