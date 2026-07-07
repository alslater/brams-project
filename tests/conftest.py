import http.client
import json
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


@pytest.fixture(autouse=True)
def _reset_screening_settings():
    """Restores mutable screening state after each test.

    HIGH_VALUE_THRESHOLD/NAME_SIMILARITY_THRESHOLD (via /settings) and
    SANCTIONED_COUNTRIES/WATCHLIST_COUNTRIES/NAME_WATCHLIST (via
    /risk-lists) are all runtime-mutable, and the server module is only
    imported once per test process, so a test that changes them would
    otherwise leak state into every test that runs after it.

    The three sets are mutated in place elsewhere (server.RISK_LISTS holds
    references to them), so they're restored with .clear()/.update() rather
    than reassignment, to preserve that same object identity.
    """
    original_threshold = server_module.HIGH_VALUE_THRESHOLD
    original_similarity = server_module.NAME_SIMILARITY_THRESHOLD
    original_sanctioned = set(server_module.SANCTIONED_COUNTRIES)
    original_watchlist = set(server_module.WATCHLIST_COUNTRIES)
    original_names = set(server_module.NAME_WATCHLIST)
    yield
    server_module.HIGH_VALUE_THRESHOLD = original_threshold
    server_module.NAME_SIMILARITY_THRESHOLD = original_similarity
    server_module.SANCTIONED_COUNTRIES.clear()
    server_module.SANCTIONED_COUNTRIES.update(original_sanctioned)
    server_module.WATCHLIST_COUNTRIES.clear()
    server_module.WATCHLIST_COUNTRIES.update(original_watchlist)
    server_module.NAME_WATCHLIST.clear()
    server_module.NAME_WATCHLIST.update(original_names)


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


def http_post_json(authority: str, path: str, payload):
    """Issues a raw POST with a JSON body against the live_server fixture.

    Returns (status, body_bytes, headers); same header semantics as http_get.
    """
    body_bytes = json.dumps(payload).encode()
    conn = http.client.HTTPConnection(authority, timeout=5)
    try:
        conn.request(
            "POST",
            path,
            body=body_bytes,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body_bytes))},
        )
        resp = conn.getresponse()
        resp_body = resp.read()
        return resp.status, resp_body, resp.headers
    finally:
        conn.close()
