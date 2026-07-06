import io
import json
import urllib.error
from unittest.mock import patch

from conftest import http_get


def make_http_error(url, code, body: bytes):
    return urllib.error.HTTPError(url, code, "Upstream Error", {}, io.BytesIO(body))


class TestUpstreamHttpErrorIsForwarded:
    def test_forwards_upstream_status_code_and_body(self, live_server):
        error_body = json.dumps({"error": "not found"}).encode()
        error = make_http_error("https://api.frankfurter.app/latest", 404, error_body)

        with patch("urllib.request.urlopen", side_effect=error):
            status, body, headers = http_get(
                live_server, "/api/convert?amount=1&from=GBP&to=USD"
            )

        assert status == 404
        assert headers.get("Content-Type") == "application/json"
        assert json.loads(body) == {"error": "not found"}


class TestUpstreamGenericFailureDoesNotLeakInternals:
    def test_generic_exception_returns_generic_502_message(self, live_server):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("connection timed out")):
            status, body, _ = http_get(live_server, "/api/convert?amount=1&from=GBP&to=USD")

        assert status == 502
        payload = json.loads(body)
        assert payload == {"error": "upstream request failed"}
        # The raw exception text must never reach the client.
        assert "connection timed out" not in body.decode()

    def test_os_error_returns_generic_502_message(self, live_server):
        with patch(
            "urllib.request.urlopen",
            side_effect=OSError("[Errno -2] Name or service not known"),
        ):
            status, body, _ = http_get(
                live_server, "/api/history?from=GBP&to=USD&end=2026-07-03&days=7"
            )

        assert status == 502
        payload = json.loads(body)
        assert payload == {"error": "upstream request failed"}
        assert "Name or service" not in body.decode()
