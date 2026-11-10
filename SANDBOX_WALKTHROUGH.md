# Repeatable manual sandbox walkthrough

Uses existing local sandbox credentials and USD 1.00 orders. No AI controller,
production calls, webhook failure injection, or real fulfillment. Keep the
runtime SQLite database and approval URL out of commits and public recordings.

```sh
python3 sandbox_walkthrough.py create
```

Open the printed approval URL and approve with the sandbox buyer. The callback
can show localhost connection refused if no server is running; this is not proof
of either approval or payment. Check fresh provider evidence with the next step.
Replace LOCAL_ORDER_ID with the printed local order ID in each command.

```sh
python3 sandbox_walkthrough.py inspect LOCAL_ORDER_ID
```

Before capture, expect PayPal APPROVED, zero captures, and NOT_VERIFIED.
Then run:

```sh
python3 sandbox_walkthrough.py lose-confirmation LOCAL_ORDER_ID
```

Type the exact requested confirmation to authorize the sandbox capture. The
harness skips local finalization after capture returns. The demonstrated state
is one completed PayPal capture, local UNKNOWN, zero fulfillment, NOT_VERIFIED.
If anything differs, inspect before proceeding. Never retry capture blindly.

```sh
python3 sandbox_walkthrough.py reconcile LOCAL_ORDER_ID
```

This starts a fresh manual investigation using a gateway that exposes only GET.
Expect SUCCEEDED, independently VERIFIED, local PAID, one fulfillment, and
unchanged capture identity/count. Reconciliation can be repeated without adding
fulfillment. Execution and verification are reported separately.

The default database is walkthrough-sandbox.sqlite3. To use another database,
put `--db PATH.sqlite3` before the subcommand consistently. Each `create` makes
a new order; it is not a resume command. For uncertain creation/capture outcomes,
retain the database and inspect rather than automatically creating replacements.

Offline validation uses a fake provider. A real sandbox run must be performed
separately; passing offline tests does not establish live provider behavior.
