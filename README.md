# IncidentLab — Payment Investigation and Verified Recovery

**Milestone 1: payment feasibility prototype.** This is a Python command-line foundation, not the finished hackathon submission. There is no AI investigator or visual dashboard yet.

Two customers see the same checkout error. One payment was never submitted; the other completed but its local confirmation was lost. Recovery must distinguish them using provider evidence.

## Start here: no accounts or packages required

Requires Python 3.10 or newer. Open Terminal in this extracted `incidentlab` folder:

```bash
python3 --version
python3 demo_offline.py
python3 -m unittest -v
```

The walkthrough uses a **fake payment provider**, clearly labeled. It demonstrates the recovery mechanics, not PayPal compatibility or AI performance. On Windows, use `py` if `python3` is unavailable.

## First real milestone: PayPal sandbox

1. Open https://developer.paypal.com/ and sign in. In the developer dashboard, use **Sandbox**, then Apps & Credentials. Create or select a sandbox REST application for a sandbox business account.
2. Locate its Client ID and Secret. Keep these on your computer. Do not paste the Secret into a chat, screenshot, public repository, or submission.
3. In Sandbox Testing Accounts, locate a separate **personal buyer test account** and its login details. Use that test buyer at approval, not your real payment account.
4. Copy `.env.example` to `.env` and put the sandbox app credentials in it:

```bash
cp .env.example .env
```

Open `.env` in a text editor. Fill in the two values, then save it. No quotation marks are required. The program loads this file from the current folder. It only sends API requests to `api-m.sandbox.paypal.com`.

### Experiment A: completed payment, lost local confirmation

```bash
python3 incidentlab.py create
```

Copy the printed `local_order_id` somewhere temporary. Open the printed `approval_url` in your browser and approve the $1.00 sandbox purchase with the personal sandbox buyer. This is test money.

The approval flow returns to `http://localhost:8765/approved`. **No callback server is included in this command-line milestone**, so a browser connection error there is expected; it does not prove whether approval succeeded. The next command checks the provider state. If PayPal rejects this return URL during order creation, stop and record the error; callback integration is an unverified compatibility point.

In the commands below, replace `LOCAL_ORDER_ID` with the ID that `create` printed; do not use the PayPal order ID.

```bash
python3 incidentlab.py capture LOCAL_ORDER_ID --fault lost-confirmation
python3 incidentlab.py inspect LOCAL_ORDER_ID
python3 incidentlab.py verify LOCAL_ORDER_ID
python3 incidentlab.py reconcile LOCAL_ORDER_ID
python3 incidentlab.py reconcile LOCAL_ORDER_ID
```

Expected: the injected fault leaves local state `UNKNOWN`; the initial verifier says `NOT_VERIFIED`. Reconciliation retrieves order details, validates completed capture evidence, and atomically records the paid order and one **simulated fulfillment**. Repeated reconciliation should still show one fulfillment. Reconciliation never calls the capture endpoint.

### Experiment B: capture never submitted

Create and approve a **new** sandbox order, then:

```bash
python3 incidentlab.py capture LOCAL_ORDER_ID --fault before-submit
python3 incidentlab.py reconcile LOCAL_ORDER_ID
```

Expected: the customer sees the same error, but reconciliation reports `NOT_VERIFIED` because there is no completed capture. To represent an operator clearing the injected configuration fault and explicitly submitting the approved payment:

```bash
python3 incidentlab.py capture LOCAL_ORDER_ID
```

The fault here is a local interception switch, not a genuine broken deployment. Replacing it with an inspectable configuration fault is future work. The agent does not exist yet and therefore cannot inspect the fault label.

## Checks and limits

- Create and capture request IDs are persisted before network mutations.
- A capture error or timeout leaves `UNKNOWN` state and blocks blind resubmission.
- `APPROVED` is not treated as paid. Pending captures are not fulfilled.
- Reconciliation checks provider order ID, local custom ID, completed capture, amount, and currency.
- Fulfillment is a local database record, not a shipment or external action.
- The read-only verifier makes a fresh provider query and checks local state. It shares the capture parser with reconciliation; it is separate operationally, not a fully independent implementation.
- Recovery of an ambiguous **create** call is not implemented. The draft is retained as `CREATE_UNKNOWN`; do not automatically replace it. This prototype has no automatic API retries.
- This supports one USD 1.00 purchase unit and one completed capture, no refunds, partial captures, or arbitrary payment flows. It is a local, sequential development tool, not production payment software.
- It is not an AI benchmark. Offline tests do not establish absence of duplicate charges in a real integration. Validate actual sandbox transaction history before making that claim.

## Next build stages

1. Record a successful sandbox lost-confirmation experiment, including redacted IDs and actual provider/local state.
2. Implement observable configuration faults, diagnostic tools, bounded action execution, and evidence logs that do not expose fault labels.
3. Add an AI investigator; compare it against fixed-action and branching rules baselines on held-out variations.
4. Build the visual store, evidence timeline, and outcome dashboard. Keep both successful and failed evaluation runs.

## Project files

- `incidentlab.py`: sandbox client, SQLite store, CLI, reconciliation, verifier.
- `test_recovery.py`: offline behavioral tests and fake provider.
- `demo_offline.py`: two-incident walkthrough.
- `.env.example`: local credential template; `.gitignore` excludes credentials and databases.

## Official references

- https://developer.paypal.com/api/orders/v2/orders-create
- https://developer.paypal.com/api/orders/v2/orders-capture
- https://developer.paypal.com/api/orders/v2/orders-get
- https://developer.paypal.com/api/rest/requests/
- https://paypalaihackathon.devpost.com/rules

API structure was checked against these references on October 20, 2026 UTC. Real sandbox calls have not yet been executed for this starter.

## License

MIT; see LICENSE. Review and understand all code before submitting it under your name.
