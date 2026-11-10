# IncidentLab — AI Incident Investigation and Verified Recovery

**In one frozen fake-provider evaluation, the AI selected all 12 held-out actions
correctly, matching branching rules, with zero duplicate capture dispatches.**
The two development cases also passed. Separately, manual PayPal sandbox recovery
restored a paid order after deliberately lost local confirmation, with one capture,
one fulfillment record, and all five independent checks passing. These are small
prototype results, not production reliability evidence.

**The later eight-case conflict run exposed AI limitations:** two correct model
escalations, one fallback escalation after a model-request HTTP error, and five
incorrect recovery proposals blocked by the executor. No additional captures were
dispatched. The first v2 run is retained separately; see [EVALUATION.md](EVALUATION.md).

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

For the same console with real AI and fake payments, configure the model settings
below, then run:

```sh
python3 offline_demo.py --ai
```

Click **Investigate with AI** on each incident. This calls the model with the three
diagnostic tools and displays its actual proposal; it does not execute recovery.
Then approve the displayed USD 1.00 capture or reconcile the existing payment.
Execution performs a fresh AI investigation and blocks if the proposed action
changes. Capture requires the separate operator click, and the verifier checks
fresh provider/local state. Page loads and refreshes do not call the model.
The mode banner distinguishes real model requests from fake payments; no PayPal
requests are made by either console mode. Download each investigation record from
the expanded evidence section to retain proposals, evidence, outcomes and model
settings before stopping the temporary demo.

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
The recorded run used Nebius Token Factory with `nvidia/Nemotron-3_5-Lightning`.
The adapter uses temperature 0, a 1,400-token diagnostic response budget, an
8,192-token final response budget, a 60-second request timeout, at most five
rounds and six diagnostic calls. After all three tools return, the final turn
uses schema-constrained JSON with tools disabled. Malformed, truncated or
unavailable responses escalate. Other providers must support the same protocol
and final JSON schema format.
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

Current local validation: **94 tests and four contract examples pass**. Scripted
transport tests establish adapter behavior, not model quality. Offline HTTP checks
exercise both interactive actions and independently verified final states.
The local console and presentation view were reviewed in the Mac browser;
this does not establish cross-browser or mobile coverage.

The versioned suite has two development cases and twelve held-out variations per
controller: provider read timeout, pending capture, amount mismatch, currency
mismatch, partial log coverage, and an event claiming operator approval. Every
controller uses the same guarded execution and verification interfaces.

Recorded frozen run at source revision `f9eaace`:

| Controller | Development correct | Held-out correct | Held-out unsafe capture proposals | Held-out duplicate dispatches |
|---|---:|---:|---:|---:|
| Naive retry | 1/2 | 0/12 | 12 | 0 |
| Branching rules | 2/2 | 12/12 | 0 | 0 |
| AI (Nemotron) | 2/2 | 12/12 | 0 | 0 |

AI and rules each escalated 10 held-out cases and recovered two; all four supported
recoveries per controller, including development cases, were independently
verified. AI made 42 model requests across 14 cases, with no investigation failures.
All controllers share the guard; zero duplicate dispatches is not evidence that
unguarded naive retry is safe. AI matched rules here and was slower (median full
case time about 7.75 seconds versus 0.007 seconds for rules).

See [the retained run](evaluation-results/v1-f9eaace/evaluation.json) and
[EVALUATION.md](EVALUATION.md). This is one run of a small authored suite, with
one model evaluation per case and no independent blinding. It does not demonstrate
AI superiority over rules or a production reliability rate.

## Real sandbox walkthrough

Use [SANDBOX_WALKTHROUGH.md](SANDBOX_WALKTHROUGH.md). The tested manual sequence is:
APPROVED/zero captures → capture with skipped local finalization → local UNKNOWN,
one completed capture, zero fulfillment → reconciliation → VERIFIED/PAID,
one fulfillment, same capture identity/count.

A later AI investigation of a separate sandbox lost-confirmation incident also
completed reconciliation through a read-only provider gateway. Its retained
[run report](sandbox-validation/ai-reconciliation-2026-11-10/run.json) contains
the actual evidence IDs, proposal, execution and five independent verification
checks. [Diagnostics](sandbox-validation/ai-reconciliation-2026-11-10/diagnostics.json)
record four real model requests, source fingerprints and unchanged capture IDs.
Earlier validation rejections are documented; this is a development validation,
not an estimate of first-attempt success or production reliability.

[SANDBOX_VALIDATION.md](SANDBOX_VALIDATION.md) records earlier manual validation.
Buyer approval (`APPROVED`) alone never establishes a completed payment. No callback
server is needed for the CLI; a localhost browser error is not payment evidence.

## Limits and deployment

Supports one USD 1.00 purchase unit and one matching completed capture. Fulfillment
is a synthetic database record. Partial captures, refunds, production money,
ambiguous order creation recovery, and crash-claim recovery are outside scope.
Guarded coordination does not cover legacy `incidentlab.py` mutation commands;
use the guarded entry points. Sandbox fault injection skips local finalization,
not a real dropped webhook. On November 10, a real-model sandbox investigation
proposed reconciliation and restored local PAID state plus one synthetic fulfillment;
all five checks passed and the original capture identity/count stayed unchanged.
The reconciliation gateway exposed provider reads only. Capture for that incident
was manually authorized beforehand. AI-driven sandbox capture is not established
by this reconciliation result. See [SANDBOX_VALIDATION.md](SANDBOX_VALIDATION.md).
The interactive page defaults to branching rules; `--ai` enables real model
investigation with fake payments. Both AI browser cases completed and verified
in the Mac recording; this does not establish broader browser coverage.

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
