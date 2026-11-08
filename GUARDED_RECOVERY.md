# Guarded recovery milestone

## Offline walkthrough

```sh
python3 demo_guarded_recovery.py
python3 -m unittest -v
python3 contracts/validate_examples.py
```

Expected: two manual-controller scenarios, SUCCEEDED execution, VERIFIED recovery,
and one capture per scenario. All 48 offline tests pass on the combined verifier
and evidence-tools branch. No credentials or existing transaction database are
used. No AI or real PayPal requests occur. Human scenario labels and action choices
in this walkthrough are not inputs to an agent and are not an evaluation result.

## Integration

- `create_guarded_order(store, gateway)` registers a new order with an UNSENT journal.
- Use the existing sandbox buyer-approval link before capture.
- `EvidenceSession` exposes CAPTURE_NOT_SENT only for a matching UNSENT journal,
  a supported local state, and no legacy capture-started event. Overall event
  coverage remains PARTIAL, because this is not a complete application log.
- The investigator returns one contract v1 proposal referencing the trusted
  session's actual observations. References must be unique, known, and recent.
- The trusted operator UI calls `approve_capture(store, local_id, amount, currency)`
  for capture. Never expose this approval function or its token to the model.
  Tokens expire after five minutes, bind to the order/provider/amount/currency,
  and are consumed before dispatch. This is a local approval primitive, not an
  authenticated multi-user approval UI; authentication remains outside this MVP.
- `execute_recovery(store, gateway, session, decision, approval_token=token)`
  permits reconcile_order, capture_approved_order, or escalate. It rechecks current
  provider evidence; proposal text and evidence IDs are not authorization.
- Each investigation can attempt at most one mutating proposal. After a blocked
  attempt, obtain fresh observations in a new session before trying again.
- Call `verify_recovery(db_path, gateway.get, local_id)` separately afterward.
  Execution SUCCEEDED never substitutes for independent verification.

## Durable uncertainty and concurrency

A persistent SQLite claim excludes other guarded workers on the same order.
A crashed worker leaves its claim in place: there is no automatic lease expiry
or takeover. Operator investigation is required before any manual cleanup.
Immediately before the capture call, approval consumption, UNKNOWN local state,
and POSSIBLY_SENT journal state commit together. The saved capture request key
is reused; no fresh capture key is generated. Timeout or lost confirmation cannot
reset the journal to UNSENT, even if a request may never have left the process.
Fresh completed provider evidence may permit reconciliation without recapture.
Local payment state and one fulfillment are committed atomically.

## Limits

This package adds a new guarded path. It does not replace the original CLI's
create/capture/reconcile commands. All final demo/agent mutations must use the new
entry points; legacy commands and external writers do not participate in claims.
Do not run them concurrently with the guarded workflow. Existing orders are not
backfilled as UNSENT. Missing journals must block capture rather than guess.
Cross-system atomicity is not claimed: provider state can change after a GET.
Only fresh approved orders with no captures and matching identity/amount may be
captured. Other states require investigation, not an automatic retry.

Fault options belong to the trusted test harness, never tool arguments. Current
fault injection is a controlled simulation, not a real infrastructure outage.
Sandbox validation, agent/report integration, and held-out evaluation remain.
Keep approval tokens, request keys, credentials, and databases out of Git/reports.

This branch builds on the verifier PR. Open its PR against feature/independent-verifier
while that PR is pending so reviewers see only the guarded-recovery changes.
