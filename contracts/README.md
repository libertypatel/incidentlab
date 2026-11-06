# IncidentLab team contract v1.0

Status: proposed interface for team review. These files add documentation, a JSON Schema, and synthetic examples. They do not change the current payment client or implement an AI investigator, verifier, recovery executor, or report renderer. Agree on this interface before building adapters against it.

## Files

| File | Consumer |
| --- | --- |
| `incident-v1.schema.json` | All owners: shape validation and supported enums |
| `evidence-01.json` | Investigator owner: synthetic diagnostic observations |
| `evidence-02.json` | Investigator owner: another synthetic diagnostic case |
| `tool-request-example.json` | Backend and investigator owners: read-only tool request |
| `run-example.json` | Report owner: complete synthetic run with decision, execution, verification, and timeline |
| `validate_examples.py` | All owners: validate the provided fixtures and evidence references |

Every example is fabricated and uses placeholder identifiers. `mode: offline` describes synthetic provider evidence, not whether a controller is AI. The report example explicitly says `controller: manual`. Do not present these examples as recorded agent or sandbox results.

The two evidence files are development examples, not held-out evaluation cases. Do not let the investigator read their filenames, expected answers, report example, or this explanation during evaluation.

## Ownership and first deliverables

- **Liberty, backend:** adapt existing local/PayPal reads to these diagnostic shapes; implement the central output boundary; separate read-only verification; expose guarded recovery entry points. Keep the existing CLI working during development.
- **Investigator teammate:** use the three read tools, return a structured decision with evidence IDs, and implement tool/action limits. Build the evaluation runner with the same interfaces for agent and baseline.
- **Report teammate:** render `run-example.json` into a polished HTML report. Display mode and controller prominently. Read execution and verification as separate results; never infer successful payment merely from the decision or execution status.

Everyone should confirm field names and enums before integration. If changes are needed, update schema, docs, and fixtures in the same pull request. Do not silently change a producer's output.

## Tool requests

Only these diagnostic tools are defined in v1:

| Tool | Arguments | Returned data |
| --- | --- | --- |
| `get_local_order` | `order_id` | Expected identity/amount/currency, normalized local payment state, local capture reference, fulfillment count |
| `get_paypal_order` | `order_id` | Fresh provider order status, one purchase unit, and all captures for that unit |
| `get_application_events` | `order_id` | Sanitized application observations plus explicit log coverage |

All tool arguments use the local order ID. The backend resolves the stored provider ID; the model cannot substitute an arbitrary provider ID, amount, or URL.

Tool responses become evidence observations with a unique `evidence_id`, tool name, observation timestamp, and `OK` or `ERROR` status. Error objects must use sanitized fixed messages. Never expose raw exception text or provider response bodies. Preserve unavailable/timeout information: failure to retrieve data is not evidence that payment never happened.

The full `evidence_bundle` is an accumulated tool transcript. Start with zero observations and append results as the controller requests tools. Complete fixture bundles are convenient development inputs, not a requirement to preload every tool result into the live investigator.

Timestamps record when the backend obtained an observation. Freshness limits are an executor policy to be implemented, not guaranteed by the schema.

## Normalize local state without revealing injected faults

- Map existing `AWAITING_APPROVAL`, `BLOCKED`, and `UNKNOWN` local states to `UNCONFIRMED` in agent-visible payment data.
- Map `PAID` to `PAID`.
- Do not map arbitrary corrupt or unsupported state to a known good state. Return a sanitized tool error and escalate.
- Keep operational state and fault metadata privately for the harness; normalization does not modify the database.

Diagnostic tools may disclose genuine transaction evidence, including that no request was dispatched or a matching completed capture exists. Do not disclose scenario labels, injection flags, module names, hidden expected actions, or timing artifacts caused by the harness.

Generate output from an allowlisted structure at one central boundary. Do not simply delete words from the existing `inspect` output. Do not pass raw `events.kind` or `events.detail` to the agent: current messages explicitly identify injected faults.

Application event messages must be generated from trusted diagnostic templates, not model text or arbitrary logs. Only assert `CAPTURE_NOT_SENT` when durable application evidence establishes it. Silence in incomplete logs does not establish non-submission. `coverage` must say `PARTIAL` or `UNAVAILABLE` when completeness cannot be guaranteed.

Both provided cases have the same initial local payment evidence. Their provider evidence differs: case 01 has an approved order without capture; case 02 has a matching completed capture. `APPROVED` alone never means paid, and absence of capture by itself is not a universal retry authorization.

## Decisions are proposals

Every proposal has a decision ID, local order ID, action, concise evidence-backed summary, and existing evidence IDs. The summary is a user-facing explanation, not hidden model reasoning.

| Action | Meaning and execution requirements |
| --- | --- |
| `reconcile_order` | Fresh matching completed payment evidence is required. Update local records atomically, with one simulated fulfillment; never submit capture. |
| `capture_approved_order` | Requires fresh buyer-approved provider state, no existing capture, durable evidence that the earlier request was not sent, and an explicit operator approval for this order/amount in v1. Use the persisted request ID and bounded executor. A model proposal alone cannot authorize payment. |
| `escalate` | Stop automatic mutation and explain what remains uncertain. No charge or fulfillment is performed. |

Pending, refunded, mismatched, conflicting, malformed, or unavailable payment evidence must block automatic recovery. Keep these outside supported automatic payment recovery in v1.

Recheck state immediately before mutation. Obtain per-order concurrency control so two controllers cannot execute competing mutations. Unknown capture outcomes must not trigger a fresh capture. Model-supplied evidence IDs are references, not authorization tokens; executor checks must resolve them against the trusted run transcript and current provider state.

These rules describe the executor to build. The existing `capture` function and this schema alone do not enforce all of them yet.

## Execution versus verification

Execution is recorded by the backend, not authored by the model. `SUCCEEDED` means the requested operation returned successfully; it does not establish verified recovery. `UNKNOWN` means the operation's outcome is uncertain. `BLOCKED` means a guard refused it. Escalation uses `NOT_EXECUTED`.

Verification is produced by a separate read-only code path using fresh PayPal evidence and local DB reads, independently parsed from the recovery code. It cannot invoke capture, reconciliation, or fulfillment. It must not consume an agent's claimed success as a fact.

- `VERIFIED`: matching completed payment, matching local state, exactly one fulfillment, and all listed checks pass.
- `NOT_VERIFIED`: available evidence establishes the recovery requirements are not satisfied.
- `INCONCLUSIVE`: missing, conflicting, or unavailable evidence prevents a reliable determination.

Provider/API failures must never be displayed as `VERIFIED`. A shape-valid verification object does not prove the evidence was actually retrieved; record provenance in the run execution system.

`completed_capture_id: null` is not sufficient alone to decide whether retry is permitted.

## Report and timeline

The report takes an `incident_run` with evidence accumulated before recovery, the proposal, backend execution result, read-only post-action verification, and ordered timeline entries. Preserve before/after observations rather than replacing pre-action data with the final state.

Use `controller: manual`, `rules`, or `agent` accurately. Real sandbox runs use `mode: sandbox`; fake-provider runs use `offline`. Display missing or inconclusive evidence explicitly. Escape all dynamic strings when generating HTML. Never run scripts or insert unescaped HTML from logs or model output.

The schema supports one proposed recovery action per run. Multi-action autonomous repair is outside v1. No arbitrary tools, shell access, refunds, new payment amounts, third scenario, or extra services are needed for this integration milestone.

## Validate the example files

From the project root, install the validation dependency in an isolated environment if needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install jsonschema
python3 contracts/validate_examples.py
```

This validates shapes and checks references in the provided run example. It does not validate actual payment safety, replace runtime guards, or establish AI performance. The existing 11 offline recovery tests remain separate.

## First integration milestone

1. All three owners review v1 and agree on any changes.
2. Backend owner produces diagnostic shapes without fault labels.
3. Investigator owner consumes those shapes and returns a validated proposal.
4. Report owner renders the same run shape with clear evidence and outcome.
5. Connect one offline run before performing another sandbox experiment.

Never commit `.env`, raw provider responses, payer details, or transaction databases. The examples here contain no real credentials, transaction IDs, or customer data.
