import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
import server


def test_external_route_is_rejected_before_control_credentials(monkeypatch):
    monkeypatch.setenv('AGENT10_BASE_URL', 'https://example.invalid')
    monkeypatch.setenv('AGENT10_CONTROL_TOKEN', '')
    monkeypatch.setenv('AGENT10_CONTROL_TOKEN_FILE', '')
    with pytest.raises(ValueError, match='loopback'):
        server._publish_agent10_agent06_asset('synthetic-asset')


def test_local_publication_rejects_redirect(monkeypatch):
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.send_response(302); self.send_header('Location', '/redirected'); self.send_header('Content-Length', '0'); self.end_headers()
        def do_GET(self):
            received.append(self.headers.get('Authorization'))
            self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
    service = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=service.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv('AGENT10_BASE_URL', f'http://127.0.0.1:{service.server_port}')
        monkeypatch.setenv('AGENT10_CONTROL_TOKEN', 'SYNTHETIC')
        with pytest.raises(RuntimeError, match='HTTP 302'):
            server._publish_agent10_agent06_asset('synthetic-asset')
        assert received == []
    finally: service.shutdown(); service.server_close()
