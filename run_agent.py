"""Run the configured AI on one existing guarded sandbox order."""
import argparse
import json
from pathlib import Path

from incidentlab import Store, PayPal, load_env
from guarded_recovery import approve_capture
from investigator import AIInvestigator, ChatTransport
from run_integration import run_incident


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--order-id', required=True)
    parser.add_argument('--output', type=Path, default=Path('/tmp/incidentlab-agent-run.json'))
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error('Existing guarded database required.')
    load_env()
    store = None
    try:
        transport = ChatTransport()
        gateway = PayPal()
        store = Store(args.db)
        def request_approval(oid, amount, currency):
            print('AI proposal requires separate operator approval:', oid, amount, currency)
            expected = 'CAPTURE ' + oid + ' ' + amount + ' ' + currency
            return approve_capture(store, oid, amount, currency) if input('Type ' + expected + ': ').strip() == expected else None
        report = run_incident(store, gateway, args.db, args.order_id, mode='sandbox',
                              controller='agent', investigate=AIInvestigator(transport), request_approval=request_approval)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        args.output.with_suffix('.metadata.json').write_text(json.dumps(transport.metadata(), indent=2) + '\n')
        print('Execution:', report['execution']['status'], '| Verification:', report['verification']['status'])
        print(args.output)
    except (Exception, KeyboardInterrupt):
        print('Run unavailable. Inspect provider and local state before retrying; execution may have occurred.')
        return 1
    finally:
        if store is not None:
            store.db.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
