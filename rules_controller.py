"""Deterministic baseline controller for contract v1 incident runs.

Same interface, tools, budget, and ability to abstain as the AI investigator:
rules_investigator(context, call_tool) returns one proposal. A proposal never
authorizes payment; the guarded executor and independent verifier decide that.
Anything outside the two supported recovery patterns escalates.
"""
from evidence_tools import ToolName

# Fixed order and count (3) so the baseline's tool usage is identical every run.
TOOL_ORDER = (ToolName.GET_LOCAL_ORDER.value, ToolName.GET_PAYPAL_ORDER.value,
              ToolName.GET_APPLICATION_EVENTS.value)

# Fixed templates only: no provider or log text reaches the report summary.
SUMMARIES = {
    'reconcile': 'PayPal shows one completed capture matching this order, amount, and '
                 'currency; the local order is unconfirmed with no fulfillment. '
                 'Reconcile local state without submitting another capture.',
    'capture': 'PayPal shows a buyer-approved order with no capture, and the application '
               'journal shows the capture request was never sent. Identity, amount, and '
               'currency match. Capture requires explicit operator approval.',
    'tool_error': 'A diagnostic source was unavailable or returned unsupported evidence; '
                  'the payment outcome is not established.',
    'already_paid': 'The local order is already marked paid; no automatic recovery applies.',
    'local_inconsistent': 'The local order has a capture reference or fulfillment while '
                          'unconfirmed; local state is inconsistent.',
    'identity_mismatch': 'PayPal order identity does not match the local order.',
    'amount_mismatch': 'PayPal amount or currency does not match the local order.',
    'multiple_captures': 'PayPal shows more than one capture; this is outside supported '
                         'automatic recovery.',
    'capture_not_completed': 'PayPal capture is not in a completed state (for example pending, '
                             'declined, or refunded); automatic recovery is not supported.',
    'capture_mismatch': 'The PayPal capture does not match the expected amount, currency, '
                        'order status, or local capture reference.',
    'dispatch_unknown': 'PayPal shows an approved order without a capture, but available '
                        'evidence cannot establish that no capture request was sent.',
    'unsupported_state': 'PayPal order status does not support automatic recovery.',
    'malformed': 'Diagnostic evidence had an unexpected shape; the payment outcome is not '
                 'established.',
}


def rules_investigator(context, call_tool):
    """Collect all three observations, then apply decide(). Tool errors propagate."""
    order_id = context['order_id']
    rows = [call_tool(tool, {'order_id': order_id}) for tool in TOOL_ORDER]
    action, reason, cited = decide(order_id, *rows)
    # decision_id follows the shared convention: the run's incident_id.
    return {'decision_id': context['incident_id'], 'order_id': order_id,
            'action': action, 'summary': SUMMARIES[reason],
            'evidence_ids': [row['evidence_id'] for row in cited]}


def decide(order_id, local, provider, events):
    """Return (action, reason_key, cited_observations) from three observations."""
    every = [local, provider, events]
    failed = [row for row in every if row.get('status') != 'OK']
    if failed:
        return 'escalate', 'tool_error', failed
    try:
        return _decide(order_id, local, provider, events)
    except (KeyError, TypeError, AttributeError):
        return 'escalate', 'malformed', every


def _decide(order_id, local, provider, events):
    every = [local, provider, events]
    mine, remote = local['data'], provider['data']
    unit, captures = remote['purchase_unit'], remote['captures']

    if mine['payment_state'] == 'PAID':
        return 'escalate', 'already_paid', [local]
    if mine['payment_state'] != 'UNCONFIRMED':
        return 'escalate', 'malformed', [local]
    if mine['fulfillment_count'] != 0:
        return 'escalate', 'local_inconsistent', [local]

    if (mine['order_id'] != order_id or unit['custom_id'] != order_id
            or not mine['provider_order_id']
            or len({mine['provider_order_id'], remote['provider_order_id'],
                    unit['provider_order_id']}) != 1):
        return 'escalate', 'identity_mismatch', [local, provider]
    expected = (mine['amount'], mine['currency'])
    if (unit['amount'], unit['currency']) != expected:
        return 'escalate', 'amount_mismatch', [local, provider]

    if len(captures) > 1:
        return 'escalate', 'multiple_captures', [local, provider]
    if len(captures) == 1:
        capture = captures[0]
        if capture['status'] != 'COMPLETED':
            return 'escalate', 'capture_not_completed', [local, provider]
        if ((capture['amount'], capture['currency']) != expected
                or remote['status'] != 'COMPLETED'
                or mine['capture_id'] not in (None, capture['capture_id'])):
            return 'escalate', 'capture_mismatch', [local, provider]
        return 'reconcile_order', 'reconcile', [local, provider]

    # No capture exists at PayPal from here on.
    if mine['capture_id'] is not None:
        return 'escalate', 'local_inconsistent', [local, provider]
    if remote['status'] != 'APPROVED':
        return 'escalate', 'unsupported_state', [local, provider]
    if not any(row['event'] == 'CAPTURE_NOT_SENT' for row in events['data']['events']):
        # Missing or partial logs never prove non-submission.
        return 'escalate', 'dispatch_unknown', every
    return 'capture_approved_order', 'capture', every
