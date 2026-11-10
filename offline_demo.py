"""One-command interactive fake-provider demo. No keys or payment network calls."""
import argparse
import json
from pathlib import Path
import secrets
import tempfile
from threading import Lock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import webbrowser

from evidence_tools import EvidenceSession
from evaluation import fixture
from guarded_recovery import approve_capture
from independent_verifier import verify_recovery
from investigator import branching_rules
from run_integration import run_incident


class Demo:
    def __init__(self, root):
        self.root, self.orders, self.lock = root, {}, Lock()
        for family in ('before-submit', 'lost-confirmation'):
            path = root / (family + '.sqlite3')
            store, gateway, oid = fixture(path, family, 'standard')
            # HTTP handlers open their own local connection.
            store.db.close()
            self.orders[oid] = {'path': path, 'gateway': gateway, 'family': family, 'report': None}

    def state(self):
        from incidentlab import Store
        cards = []
        for oid, item in self.orders.items():
            store = Store(item['path'])
            try:
                session = EvidenceSession(store, item['gateway'], oid, mode='offline')
                proposed = branching_rules(session.bundle(), session.call)
                cards.append({'order_id': oid, 'family': item['family'], 'amount': '1.00', 'currency': 'USD',
                    'evidence': session.bundle(), 'proposal': proposed, 'report': item['report'],
                    'verification': verify_recovery(item['path'], item['gateway'].get, oid),
                    'capture_count': item['gateway'].capture_calls})
            finally:
                store.db.close()
        return cards

    def execute(self, oid, approve):
        from incidentlab import Store
        item = self.orders[oid]
        store = Store(item['path'])
        try:
            item['report'] = run_incident(store, item['gateway'], item['path'], oid,
                mode='offline', controller='rules', investigate=branching_rules,
                request_approval=(lambda order, amount, currency: approve_capture(store, order, amount, currency)) if approve else None)
        finally:
            store.db.close()


def serve(port=0, open_browser=True):
    with tempfile.TemporaryDirectory(prefix='incidentlab-demo-') as folder:
        demo, token = Demo(Path(folder)), secrets.token_urlsafe(24)
        page = (Path(__file__).with_name('report.html')).read_text().replace('__TOKEN__', token)
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
                if (self.path != '/api/execute' or self.headers.get('Host') != self.server.expected_host
                        or self.headers.get('X-Demo-Token') != token
                        or self.headers.get('Origin') != 'http://' + self.server.expected_host):
                    return self.respond({'error': 'Request rejected'}, 403)
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 1024:
                        raise ValueError()
                    body = json.loads(self.rfile.read(length))
                    if set(body) != {'order_id', 'approve'} or type(body['approve']) is not bool:
                        raise ValueError()
                    with demo.lock:
                        demo.execute(body['order_id'], body['approve'])
                        self.respond(demo.state())
                except Exception:
                    self.respond({'error': 'Execution unavailable; inspect current state.'}, 400)
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        server.expected_host = '127.0.0.1:' + str(server.server_port)
        url = 'http://' + server.expected_host
        print('OFFLINE FAKE PROVIDER | branching rules | no AI or PayPal calls', flush=True)
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
    args = parser.parse_args()
    serve(args.port, not args.no_open)
