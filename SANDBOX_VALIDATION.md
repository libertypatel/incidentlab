# Manual PayPal sandbox validation

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

AI investigator integration, report rendering, and agent evaluation
remain outstanding. Credentials, payer details, and runtime databases
are excluded from this document.
