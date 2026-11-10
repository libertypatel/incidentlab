# PayPal sandbox validation

Date: November 8, 2026
Controller: manual; no AI investigator invoked.
Environment: PayPal sandbox, USD 1.00 per order.

## Approved order without a capture

Before execution: PayPal APPROVED, zero captures, local AWAITING_APPROVAL.

A human-authorized guarded capture returned SUCCEEDED.
Independent verification returned VERIFIED, local payment became PAID,
and exactly one fulfillment record existed. All five checks passed.

## Completed capture with lost local confirmation

The guarded executor captured a second sandbox order and deliberately
skipped saving local confirmation using the lost-confirmation harness option.

Before reconciliation:
- Execution UNKNOWN.
- PayPal COMPLETED with one completed capture.
- Local status UNKNOWN, zero fulfillment records.
- Independent verification NOT_VERIFIED.

A fresh manual investigation proposed reconcile_order.
The reconciliation gateway prohibited capture calls.

After reconciliation:
- Execution SUCCEEDED.
- Independent verification VERIFIED; all five checks passed.
- Local payment PAID, exactly one fulfillment record.
- PayPal capture count remained one.

## Sandbox compatibility fix

PayPal returned an amount object containing breakdown, currency_code,
and value. Whole-object equality incorrectly blocked the first attempt
before capture dispatch.

The executor now compares order identity, amount value, and currency
explicitly. Regression tests cover extra breakdown fields and rejection
of wrong amounts, currencies, and local order identities.

Offline validation after the fix: 60 tests passed on the integration branch.

## Scope

These were two manual sandbox walkthroughs, not an AI evaluation or
a production reliability benchmark. The first validated approved-order
capture; it did not inject a checkout failure. The second deliberately
injected lost local confirmation after capture.

At the time of the November 8 manual validation, AI integration, report rendering
and agent evaluation remained outstanding. Later validation is recorded below. Credentials, payer details, and runtime databases
are excluded from this document.


## AI-guided reconciliation — November 10, 2026

Adapter fix committed as `f176340`; source fingerprints in the retained diagnostics
match the evaluated investigator, coordinator and evidence-tools files.

- [Run report](sandbox-validation/ai-reconciliation-2026-11-10/run.json)
- [Model and capture diagnostics](sandbox-validation/ai-reconciliation-2026-11-10/diagnostics.json)

A human approved USD 1.00 sandbox capture with deliberate skipped local
finalization. PayPal showed COMPLETED with one completed capture, while the local
order was UNKNOWN with no capture ID and zero synthetic fulfillment records.
The AI received normalized local-order, provider-order and application-event
evidence through the same three bounded diagnostic tools.

The recovery run used `run_incident(..., mode="sandbox", controller="agent")`
with `AIInvestigator(ChatTransport())`, no capture approval callback, and
`ReadOnlyGateway(PayPal())`. This gateway exposes only provider GET; the executor
can repair local state but has no provider capture method in this run.

| Check | Observed result |
|---|---|
| AI proposal | `reconcile_order`, citing all three observed evidence IDs |
| Execution | SUCCEEDED |
| Independent verification | VERIFIED; all five checks PASS |
| Local payment state | PAID |
| Synthetic fulfillment count | 0 before → 1 after |
| Provider capture count | 1 before → 1 after |
| Provider capture identity | Unchanged |
| Real model | `nvidia/Nemotron-3_5-Lightning` via Nebius Token Factory |
| Model requests | 4: three tool-call responses and one final proposal |

The uploaded report was checked against the incident-run schema, decision/evidence
references, all five verification results, capture-ID consistency and recorded
source fingerprints. No API keys, payer details or raw provider responses occur
in these normalized artifacts.

Two earlier coordinator attempts failed investigation validation before recovery.
A separate read-only diagnostic passed between those attempts. One failed attempt's
saved diagnostics recorded a rejected tool request and unchanged capture identity.
Binding each tool's order-ID schema to the current local order and validating
arguments before dispatch was added before the successful run. The exact rejected
arguments from the earlier requests were not retained, so local/provider ID
confusion remains a likely cause, not a proven root cause. Keep those failures in
the development history; do not describe this as first-attempt success.

This validates one real-AI sandbox reconciliation with synthetic fulfillment.
The preceding capture was manual. It does not establish AI-driven sandbox capture,
live-money recovery, a real dropped webhook, or a production reliability rate.
The frozen fake-provider evaluation at `f9eaace` used an earlier adapter version;
its original 12/12 held-out result is retained separately and has not been rescored
for this later binding change. Current offline validation is 75 tests and four
contract examples passing. The real-AI fake-provider console also completed both
cases in the Mac browser recording, with 2/2 independently verified.
