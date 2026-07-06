import http.client
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import server as server_module  # noqa: E402  (import after sys.path setup)


class FakeUpstreamResponse:
    """Mimics the object returned by urllib.request.urlopen(...) as a context manager."""

    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def live_server(monkeypatch):
    """Starts the real Handler on an ephemeral port, serving from the project root."""
    monkeypatch.chdir(PROJECT_ROOT)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_module.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    try:
        yield f"127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def http_get(authority: str, path: str):
    """Issues a raw GET against the live_server fixture and returns (status, body_bytes, headers).

    headers is an email.message.Message (via HTTPResponse.headers), so lookups
    like headers.get("Content-Type") are case-insensitive.
    """
    conn = http.client.HTTPConnection(authority, timeout=5)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, body, resp.headers
    finally:
        conn.close()
