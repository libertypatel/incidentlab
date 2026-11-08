# Independent verifier milestone

## Run offline

Activate the existing virtual environment, then run:

```sh
python3 demo_verifier.py
python3 -m unittest -v
```

The demo prints NOT_VERIFIED before reconciliation, VERIFIED after reconciliation,
and INCONCLUSIVE when provider evidence cannot be fetched. Capture call count
remains one. The demo uses a temporary database and fake provider; it does not
read your credentials or your existing transaction database.

On main plus these four files, 24 tests should pass: 13 new verifier tests and the
11 original recovery tests. If the evidence-tools branch has also been merged,
its nine tests should also run, giving 33 tests.

## Integration API

```python
from independent_verifier import verify_recovery
result = verify_recovery(database_path, gateway.get, local_order_id)
```

Use the real sandbox gateway's GET method for a sandbox run and the fake provider
for offline runs. The application supplies this dependency; do not let a model
choose the callable or supply a cached response in its place. The result is a
contract v1 verification object. An unusable local database/order raises a fixed
VerificationUnavailable error: the caller must stop and report verification
unavailable, never invent identity fields to fabricate a valid result.

The verifier opens SQLite with mode=ro and query_only=ON. It makes a fresh provider
read on each call, checks identity, order and capture amounts/currencies, completed
status, local capture reference, and one matching fulfillment. It uses its own
parser, with no import of recovery's payment_evidence, reconcile, capture, or
verify. Provider errors are sanitized and cannot produce VERIFIED. Missing or
ambiguous evidence is preserved as UNKNOWN checks and an INCONCLUSIVE result.
Multiple captures are outside this MVP. Explicit pending/refunded payment states
cannot verify. A local identity/amount change during the provider request also
makes the result INCONCLUSIVE.

## Limits

This is a new callable, not yet wired into the original incidentlab.py CLI or the
agent/report runner. The original verify command still uses the original shared
parser until integration replaces that path. No payment mutation or execution
policy was added. Fresh reads are observations, not a guarantee that remote state
cannot change afterward. The verifier does not claim production reliability.

All current tests use synthetic provider data. Real sandbox validation and full
run/report integration remain to be done. Keep real response bodies, credentials,
and transaction databases out of Git and reports.
