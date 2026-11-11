"""Interactive fake-provider demo; optional real AI, never PayPal network calls."""
import argparse
import json
from pathlib import Path
import secrets
import tempfile
from threading import Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import webbrowser

from evidence_tools import EvidenceSession, TOOLS
from evaluation import fixture
from guarded_recovery import approve_capture
from independent_verifier import verify_recovery
from investigator import AIInvestigator, ChatTransport, branching_rules
from run_integration import run_incident, _validator


class Demo:
    def __init__(self, root, investigator=None):
        self.root, self.orders, self.lock = root, {}, Lock()
        self.investigator = investigator
        self.controller = 'agent' if investigator is not None else 'rules'
        for family in ('before-submit', 'lost-confirmation'):
            path = root / (family + '.sqlite3')
            store, gateway, oid = fixture(path, family, 'standard')
            # HTTP handlers open their own local connection.
            store.db.close()
            self.orders[oid] = {'path': path, 'gateway': gateway, 'family': family, 'report': None, 'preview': None, 'execution_model_settings': None}

    def state(self):
        from incidentlab import Store
        cards = []
        for oid, item in self.orders.items():
            store = Store(item['path'])
            try:
                session = EvidenceSession(store, item['gateway'], oid, mode='offline')
                if self.controller == 'rules':
                    proposed = branching_rules(session.bundle(), session.call)
                else:
                    for tool in TOOLS:
                        session.call(tool, {'order_id': oid})
                    proposed = item['preview']['decision'] if item['preview'] else None
                cards.append({'order_id': oid, 'family': item['family'], 'amount': '1.00', 'currency': 'USD',
                    'evidence': session.bundle(), 'proposal': proposed, 'report': item['report'],
                    'verification': verify_recovery(item['path'], item['gateway'].get, oid),
                    'capture_count': item['gateway'].capture_calls, 'controller': self.controller,
                    'model': getattr(getattr(self.investigator, 'transport', None), 'model', None),
                    'investigation': item['preview'],
                    'execution_model_settings': item['execution_model_settings']})
            finally:
                store.db.close()
        return cards

    def investigate(self, oid):
        from incidentlab import Store
        if self.controller != 'agent':
            raise ValueError('AI mode is not enabled.')
        item = self.orders[oid]
        if item['preview'] is not None or item['report'] is not None:
            raise ValueError('Investigation already recorded.')
        store = Store(item['path'])
        try:
            session = EvidenceSession(store, item['gateway'], oid, mode='offline')
            context = {k: v for k, v in session.bundle().items() if k != 'observations'}
            proposal = self.investigator(context, session.call)
            _validator('decision').validate(proposal)
            observations = session.bundle()['observations']
            if (proposal['order_id'] != oid or proposal['decision_id'] != context['incident_id']
                    or not set(proposal['evidence_ids']) <= {r['evidence_id'] for r in observations}):
                raise ValueError('Invalid proposal references.')
            transport = getattr(self.investigator, 'transport', None)
            item['preview'] = {'decision': proposal, 'evidence': session.bundle(),
                'model_settings': json.loads(json.dumps(transport.metadata())) if transport else None,
                'failure_category': getattr(self.investigator, 'last_error', None)}
        finally:
            store.db.close()

    def execute(self, oid, approve):
        from incidentlab import Store
        item = self.orders[oid]
        if item['report'] and item['report']['execution']['status'] == 'SUCCEEDED':
            raise ValueError('Recovery already executed.')
        if self.controller == 'agent' and item['preview'] is None:
            raise ValueError('Investigate before execution.')
        store = Store(item['path'])
        try:
            def investigate_current(context, call_tool):
                proposal = self.investigator(context, call_tool)
                if proposal['action'] != item['preview']['decision']['action']:
                    raise ValueError('Proposal changed; no execution authorized.')
                return proposal
            item['report'] = run_incident(store, item['gateway'], item['path'], oid,
                mode='offline', controller=self.controller,
                investigate=investigate_current if self.controller == 'agent' else branching_rules,
                request_approval=(lambda order, amount, currency: approve_capture(store, order, amount, currency)) if approve else None)
            transport = getattr(self.investigator, 'transport', None)
            item['execution_model_settings'] = json.loads(json.dumps(transport.metadata())) if transport else None
        finally:
            store.db.close()


def serve(port=0, open_browser=True, ai=False):
    investigator = None
    if ai:
        from incidentlab import load_env
        load_env()
        investigator = AIInvestigator(ChatTransport())
    with tempfile.TemporaryDirectory(prefix='incidentlab-demo-') as folder:
        demo, token = Demo(Path(folder), investigator=investigator), secrets.token_urlsafe(24)
        page = (Path(__file__).with_name('report.html')).read_text(encoding='utf-8').replace('__TOKEN__', token)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, value, code=200, html=False):
                body = value.encode() if html else json.dumps(value).encode()
                self.send_response(code)
                self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.headers.get('Host') != self.server.expected_host:
                    return self.respond({'error': 'Invalid host'}, 403)
                if self.path == '/':
                    return self.respond(page, html=True)
                if self.path == '/api/state':
                    with demo.lock:
                        return self.respond(demo.state())
                self.respond({'error': 'Not found'}, 404)

            def do_POST(self):
                if (self.path not in {'/api/execute', '/api/investigate'} or self.headers.get('Host') != self.server.expected_host
                        or self.headers.get('X-Demo-Token') != token
                        or self.headers.get('Origin') != 'http://' + self.server.expected_host):
                    return self.respond({'error': 'Request rejected'}, 403)
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 1024:
                        raise ValueError()
                    body = json.loads(self.rfile.read(length))
                    expected = {'order_id', 'approve'} if self.path == '/api/execute' else {'order_id'}
                    if set(body) != expected or ('approve' in body and type(body['approve']) is not bool):
                        raise ValueError()
                    with demo.lock:
                        if self.path == '/api/investigate':
                            demo.investigate(body['order_id'])
                        else:
                            demo.execute(body['order_id'], body['approve'])
                        self.respond(demo.state())
                except Exception:
                    self.respond({'error': 'Execution unavailable; inspect current state.'}, 400)
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        server.expected_host = '127.0.0.1:' + str(server.server_port)
        url = 'http://' + server.expected_host
        print('FAKE PAYMENTS | REAL AI | no PayPal calls' if ai else
              'OFFLINE FAKE PROVIDER | branching rules | no AI or PayPal calls', flush=True)
        print(url, flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--ai', action='store_true', help='Use configured real AI with fake payments; model calls may incur charges.')
    args = parser.parse_args()
    serve(args.port, not args.no_open, ai=args.ai)
