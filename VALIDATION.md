# Milestone 1 validation

Executed in the build environment with Python 3.12.14.

## Passed: offline behavioral checks

`python3 -m unittest -v`: 11 tests passed.

- Lost local confirmation is recovered without another capture request.
- Repeated reconciliation retains one simulated fulfillment record.
- Two identical customer errors correspond to different provider states.
- An explicitly cleared pre-submission fault permits capture.
- Pending captures do not fulfill.
- Wrong amounts and currencies are rejected.
- Wrong local-order identity is rejected.
- Buyer approval alone is not payment.
- Unknown capture outcomes block blind resubmission.
- A simulated network timeout after payment can be reconciled.
- The read-only verifier detects missing fulfillment.

`python3 demo_offline.py`: both incident walkthroughs completed, each with one fake-provider capture call after recovery.

## Not yet verified

- Authentication, create, buyer approval, capture, and order retrieval against PayPal sandbox.
- Acceptance of the localhost return/cancel URLs for the chosen sandbox app.
- Provider/local consistency using actual sandbox records.
- Duplicate-payment protection in a real integration.
- AI diagnostic quality or improvement over deterministic baselines.
- Hosted deployment, a graphical dashboard, or user testing.

The fake provider deliberately exercises supported response shapes. It cannot validate PayPal API compatibility. These results are implementation checks, not hackathon evaluation results.
