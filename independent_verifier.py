"""Independent, read-only verification for IncidentLab contract v1.

The injected fetch_order callable must perform a fresh provider GET. No agent
claim, cached evidence bundle, recovery function, or payment parser is accepted.
"""
from contextlib import closing
from decimal import Decimal
from pathlib import Path
import re
import sqlite3

CHECKS = ('provider_payment_completed', 'order_identity_matches',
          'amount_currency_match', 'local_state_matches', 'single_fulfillment')


class VerificationUnavailable(Exception):
    """Local context is unusable; a contract result cannot be constructed."""


def _open_readonly(path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA query_only=ON')
    return connection


def _local(connection, order_id):
    row = connection.execute(
        'SELECT id,provider_id,status,capture_id,amount,currency FROM orders WHERE id=?',
        (order_id,)).fetchone()
    if row is None:
        raise ValueError('Missing order')
    order = dict(row)
    if not isinstance(order['provider_id'], str) or not order['provider_id']:
        raise ValueError('Missing provider ID')
    if order['status'] not in {'PAID', 'AWAITING_APPROVAL', 'BLOCKED', 'UNKNOWN'}:
        raise ValueError('Unsupported local state')
    _amount({'value': order['amount'], 'currency_code': order['currency']})
    return order


def _amount(value):
    amount, currency = value['value'], value['currency_code']
    if not isinstance(amount, str) or not re.fullmatch(r'\d+\.\d{2}', amount):
        raise ValueError('Invalid monetary value')
    if not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency):
        raise ValueError('Invalid currency')
    return Decimal(amount), currency


def _identifier(value):
    if not isinstance(value, str) or not value:
        raise ValueError('Missing identifier')
    return value


def _provider_checks(order, remote):
    """Independent parser: do not import recovery's payment_evidence helper."""
    checks = {name: 'UNKNOWN' for name in CHECKS[:3]}
    remote_id = _identifier(remote['id'])
    units = remote['purchase_units']
    if not isinstance(units, list) or len(units) != 1:
        return checks, None
    unit = units[0]
    custom_id = _identifier(unit['custom_id'])
    checks['order_identity_matches'] = (
        'PASS' if remote_id == order['provider_id'] and custom_id == order['id'] else 'FAIL')
    unit_amount = _amount(unit['amount'])
    expected = _amount({'value': order['amount'], 'currency_code': order['currency']})
    captures = unit.get('payments', {}).get('captures', [])
    if not isinstance(captures, list):
        raise ValueError('Invalid captures')
    status = remote['status']
    if not captures:
        if status in {'CREATED', 'APPROVED', 'VOIDED', 'PAYER_ACTION_REQUIRED'}:
            checks['provider_payment_completed'] = 'FAIL'
        checks['amount_currency_match'] = 'PASS' if unit_amount == expected else 'FAIL'
        return checks, None
    if len(captures) != 1:
        return checks, None  # Multiple captures are outside supported recovery.
    capture = captures[0]
    capture_id = _identifier(capture['id'])
    capture_amount = _amount(capture['amount'])
    checks['amount_currency_match'] = 'PASS' if unit_amount == expected == capture_amount else 'FAIL'
    capture_status = capture['status']
    if status == 'COMPLETED' and capture_status == 'COMPLETED':
        # Explicit refund evidence invalidates this MVP's paid-order claim.
        if unit.get('payments', {}).get('refunds'):
            checks['provider_payment_completed'] = 'FAIL'
            return checks, None
        checks['provider_payment_completed'] = 'PASS'
        return checks, capture_id
    if capture_status in {'PENDING', 'DECLINED', 'FAILED', 'REFUNDED', 'PARTIALLY_REFUNDED'}:
        checks['provider_payment_completed'] = 'FAIL'
    return checks, None


def verify_recovery(db_path, fetch_order, order_id):
    """Read a fresh provider response, then a consistent local SQLite snapshot.

    fetch_order(provider_order_id) is a trusted application dependency, not a
    model-selected function. Provider errors are INCONCLUSIVE with no raw text.
    Unusable local context raises a fixed VerificationUnavailable error instead
    of inventing order identity or local payment state to satisfy the schema.
    """
    try:
        with closing(_open_readonly(db_path)) as connection:
            initial = _local(connection, order_id)
            try:
                remote = fetch_order(initial['provider_id'])
            except Exception:
                remote = None
            connection.execute('BEGIN')
            order = _local(connection, order_id)
            rows = connection.execute('SELECT capture_id FROM fulfillment WHERE order_id=?', (order_id,)).fetchall()
            checks = {name: 'UNKNOWN' for name in CHECKS}
            capture_id = None
            # Do not validate a response against identity/amount changed mid-read.
            same_context = all(initial[key] == order[key] for key in ('id', 'provider_id', 'amount', 'currency'))
            if remote is not None and same_context:
                try:
                    provider, capture_id = _provider_checks(order, remote)
                    checks.update(provider)
                except (KeyError, TypeError, ValueError, AttributeError, IndexError):
                    pass
            if capture_id is not None:
                checks['local_state_matches'] = 'PASS' if order['status'] == 'PAID' and order['capture_id'] == capture_id else 'FAIL'
                checks['single_fulfillment'] = 'PASS' if len(rows) == 1 and rows[0]['capture_id'] == capture_id else 'FAIL'
            else:
                if order['status'] != 'PAID':
                    checks['local_state_matches'] = 'FAIL'
                if len(rows) != 1:
                    checks['single_fulfillment'] = 'FAIL'
            # Unavailable/conflicting evidence takes precedence over local failures.
            values = list(checks.values())
            outcome = 'INCONCLUSIVE' if 'UNKNOWN' in values else ('VERIFIED' if all(v == 'PASS' for v in values) else 'NOT_VERIFIED')
            # A known unpaid provider is definitively not recovered even when a
            # completed capture ID is unavailable for comparing local references.
            if checks['provider_payment_completed'] == 'FAIL':
                outcome = 'NOT_VERIFIED'
            return {
                'status': outcome, 'provider_order_id': order['provider_id'],
                'completed_capture_id': capture_id,
                'local_payment_state': 'PAID' if order['status'] == 'PAID' else 'UNCONFIRMED',
                'fulfillment_count': len(rows),
                'checks': [{'name': name, 'status': checks[name]} for name in CHECKS],
            }
    except (sqlite3.Error, ValueError, TypeError, KeyError, OSError):
        raise VerificationUnavailable('Local verification context is unavailable or unsupported.') from None
