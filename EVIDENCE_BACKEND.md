# Evidence backend milestone

Adds `evidence_tools.EvidenceSession(store, gateway, order_id, mode="offline")`.
Call `session.call(tool_name, {"order_id": order_id})` for each requested read tool;
`session.bundle()` returns a copy of the accumulated contract v1 transcript.
Use mode="sandbox" only with the real sandbox provider. The mode is selected by trusted application code, not by the model.

## Run

Activate your existing virtual environment, then:

```sh
python3 -m pip install jsonschema
python3 demo_evidence.py
python3 -m unittest -v
```

Expected: two synthetic evidence bundles and 20 passing tests. No network requests.
The demo's fake provider reuses the existing offline test provider.

## Boundaries and remaining work

Only local order data and fresh provider reads are exposed through allowlisted
structures. Private request keys, payer objects, raw logs, exception text, and
injection names are omitted. Invalid requests are rejected before provider access.
Missing/malformed data becomes an error rather than an invented empty capture list.
Identity/amount mismatches in otherwise supported provider shapes are preserved.

Application-event evidence is deliberately PARTIAL with an empty event list.
The starter has no authoritative dispatch journal: capture_started is written
before the network request and cannot prove dispatch. Missing logs cannot prove
a request was never sent. A guarded dispatch journal/executor is still needed
before automatic capture proposals can be safely executed.

This milestone does not implement recovery execution, an independent verifier,
an AI investigator, or complete resistance to timing/structural leakage.
The existing payment CLI and contract files are unchanged. Tests here use fake
provider data; live sandbox compatibility remains to be tested.
