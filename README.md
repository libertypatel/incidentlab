# IncidentLab — AI Incident Investigation and Verified Recovery

**Manual PayPal sandbox validation restored a paid order after deliberately lost
local confirmation, with one capture and one fulfillment record.** All five
independent verification checks passed. This is sandbox evidence, not a production
reliability or AI performance claim.

Two customers see the same checkout error. One capture was never submitted; the
other completed but local confirmation was lost. IncidentLab investigates the
payment evidence and proposes a bounded recovery.

**AI proposes, code decides, human approves, verifier confirms.**

## Run the interactive offline demo

Python 3.10+; install the contract validator once:

```sh
python3 -m pip install jsonschema==4.26.0
python3 offline_demo.py
```

The command opens a local report with two incidents side by side, evidence,
proposals, explicit **Approve capture · USD 1.00**, execution outcomes, and
independent verification checks. Press Ctrl+C to stop; restarting resets the demo.
Use `--no-open` to print the URL without launching a browser.

**This demo uses a fake provider and a branching-rules controller, with no keys,
AI inference, PayPal requests, or real fulfillment.** Its temporary database is
discarded on exit. Approval is meaningful only within this simulated demo.

## Architecture

`investigate(context, call_tool)` receives only three read-only diagnostic tools:
`get_local_order`, `get_paypal_order`, `get_application_events`.

1. The investigator collects evidence and returns a schema-valid decision with
   evidence IDs and a plain-English operator summary.
2. `run_incident` validates the proposal and trusted evidence references.
3. The guarded executor checks payment identity, amount, currency and durable
   submission history. Capture requires separate, expiring operator approval.
4. The independent verifier parses a fresh provider GET and reads SQLite through
   its own read-only connection. Execution success and VERIFIED remain separate.

Allowed proposals: `capture_approved_order`, `reconcile_order`, `escalate`.
No generated scripts, arbitrary API tools, refunds, or model-created approvals.
Application messages are untrusted data, even if they claim human approval.

## Connect a real AI investigator

`investigator.AIInvestigator` implements the callback with bounded Chat Completions
function-tool calls. The transport is injected, so teammate adapters can replace
it. Configure these locally in the environment or ignored `.env`:

```text
INCIDENTLAB_LLM_URL=https://YOUR_PROVIDER/v1/chat/completions
INCIDENTLAB_MODEL=YOUR_EXACT_MODEL_ID
INCIDENTLAB_LLM_KEY=YOUR_KEY
```

The provider must support this tool-call protocol and the documented settings.
No compatibility with a particular model has been established yet. The adapter
uses temperature 0, max_tokens 1400, 30-second request timeout, at most five
rounds and six diagnostic calls. Malformed/unavailable responses escalate.
Credentials, approval tokens, and raw provider errors are not model inputs.

To investigate an existing guarded sandbox order (requires local sandbox PayPal
credentials as documented in `.env.example`):

```sh
python3 run_agent.py --db guarded-sandbox.sqlite3 --order-id LOCAL_ORDER_ID
```

This contacts the external model and PayPal sandbox. Capture needs a separate
terminal confirmation showing order ID, amount, and currency. Inspect uncertain
outcomes before retrying. The JSON report and model/settings/usage sidecar default
to `/tmp`; retain them privately for evaluation. Never commit runtime credentials.

## Evaluation and tests

```sh
python3 -m unittest discover -q
python3 contracts/validate_examples.py
python3 evaluation.py
# Optional paid/external model calls on synthetic offline cases:
python3 evaluation.py --ai
```

Current local validation: **66 tests and four contract examples pass**. Scripted
transport tests establish adapter behavior, not model quality. Offline HTTP checks
exercise both interactive actions and independently verified final states.
Browser rendering still needs local visual review.

The versioned suite has two development cases and twelve held-out variations per
controller: provider read timeout, pending capture, amount mismatch, currency
mismatch, partial log coverage, and an event claiming operator approval. Every
controller uses the same guarded execution and verification interfaces.

Initial fake-provider results: branching rules selected 14/14 expected actions;
naive retry selected 1/14 and proposed unsafe capture in 13/14. Both had zero
observed duplicate captures because they share the guard. **AI n=0 until a real
model evaluation is run.** See [EVALUATION.md](EVALUATION.md) for definitions and
limits. These small authored fixtures are not a blinded independent benchmark.

## Real sandbox walkthrough

Use [SANDBOX_WALKTHROUGH.md](SANDBOX_WALKTHROUGH.md). The tested manual sequence is:
APPROVED/zero captures → capture with skipped local finalization → local UNKNOWN,
one completed capture, zero fulfillment → reconciliation → VERIFIED/PAID,
one fulfillment, same capture identity/count.

[SANDBOX_VALIDATION.md](SANDBOX_VALIDATION.md) records earlier manual validation.
Buyer approval (`APPROVED`) alone never establishes a completed payment. No callback
server is needed for the CLI; a localhost browser error is not payment evidence.

## Limits and deployment

Supports one USD 1.00 purchase unit and one matching completed capture. Fulfillment
is a synthetic database record. Partial captures, refunds, production money,
ambiguous order creation recovery, and crash-claim recovery are outside scope.
Guarded coordination does not cover legacy `incidentlab.py` mutation commands;
use the guarded entry points. Sandbox fault injection skips local finalization,
not a real dropped webhook. AI live integration and evaluation remain unverified.

AG Grid Community is an optional incident-table enhancement, not required by the
local demo. We have not claimed sponsor-prize eligibility. Keep the no-network
local page usable if adding it. Render is a candidate for a hosted fake-provider
preview; do not deploy the local mutable demo as a shared public payment service.
Render free instances have ephemeral storage and can sleep. A persistent sandbox
service needs authentication, per-session state, durable storage, and a separate
review. No hosted deployment is included here.

Official references:
- https://developer.paypal.com/api/orders/v2/orders-get
- https://developer.paypal.com/api/orders/v2/orders-capture
- https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
- https://www.ag-grid.com/eula/community/
- https://render.com/docs/free

MIT; see LICENSE. Review and understand the implementation before submission.
