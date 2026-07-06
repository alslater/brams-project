import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import FakeUpstreamResponse, http_get


class TestConvertEndpoint:
    def test_valid_request_returns_upstream_body(self, live_server):
        upstream_body = json.dumps(
            {"amount": 100.0, "base": "GBP", "date": "2026-07-03", "rates": {"USD": 133.55}}
        ).encode()

        with patch("urllib.request.urlopen", return_value=FakeUpstreamResponse(upstream_body)):
            status, body, headers = http_get(
                live_server, "/api/convert?amount=100&from=GBP&to=USD"
            )

        assert status == 200
        assert headers.get("Content-Type") == "application/json"
        assert json.loads(body) == json.loads(upstream_body)

    def test_forwards_urlencoded_query_params_to_upstream(self, live_server):
        captured_url = {}

        def fake_urlopen(req, timeout=10):
            captured_url["url"] = req.full_url
            return FakeUpstreamResponse(b'{"rates": {}}')

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            status, _, _ = http_get(live_server, "/api/convert?amount=100&from=GBP&to=USD,EUR")

        assert status == 200
        parsed = urlparse(captured_url["url"])
        params = parse_qs(parsed.query)
        assert params == {"amount": ["100"], "from": ["GBP"], "to": ["USD,EUR"]}

    def test_rejects_non_numeric_amount(self, live_server):
        with patch("urllib.request.urlopen") as mock_urlopen:
            status, body, _ = http_get(live_server, "/api/convert?amount=abc&from=GBP&to=USD")

        mock_urlopen.assert_not_called()
        assert status == 400
        assert "error" in json.loads(body)

    def test_rejects_lowercase_from_currency(self, live_server):
        with patch("urllib.request.urlopen") as mock_urlopen:
            status, _, _ = http_get(live_server, "/api/convert?amount=1&from=gbp&to=USD")

        mock_urlopen.assert_not_called()
        assert status == 400

    def test_rejects_malformed_to_currency_list(self, live_server):
        with patch("urllib.request.urlopen") as mock_urlopen:
            status, _, _ = http_get(live_server, "/api/convert?amount=1&from=GBP&to=USD;rm")

        mock_urlopen.assert_not_called()
        assert status == 400

    def test_query_injection_attempt_is_rejected(self, live_server):
        with patch("urllib.request.urlopen") as mock_urlopen:
            status, _, _ = http_get(
                live_server, "/api/convert?amount=1&from=GBP&to=USD%26evil%3D1"
            )

        mock_urlopen.assert_not_called()
        assert status == 400

    def test_missing_params_fall_back_to_defaults(self, live_server):
        # amount defaults to "1" and from defaults to "USD", both of which are valid,
        # so the request should succeed using those defaults.
        captured_url = {}

        def fake_urlopen(req, timeout=10):
            captured_url["url"] = req.full_url
            return FakeUpstreamResponse(b'{"rates": {}}')

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            status, _, _ = http_get(live_server, "/api/convert?to=USD")

        assert status == 200
        params = parse_qs(urlparse(captured_url["url"]).query)
        assert params == {"amount": ["1"], "from": ["USD"], "to": ["USD"]}


class TestHistoryEndpoint:
    def test_valid_request_returns_upstream_body(self, live_server):
        upstream_body = json.dumps(
            {"amount": 1.0, "base": "GBP", "rates": {"2026-07-03": {"JPY": 215.21}}}
        ).encode()

        with patch("urllib.request.urlopen", return_value=FakeUpstreamResponse(upstream_body)):
            status, body, _ = http_get(
                live_server, "/api/history?from=GBP&to=JPY&end=2026-07-03&days=7"
            )

        assert status == 200
        assert json.loads(body) == json.loads(upstream_body)

    def test_builds_correct_date_range_and_query(self, live_server):
        captured_url = {}

        def fake_urlopen(req, timeout=10):
            captured_url["url"] = req.full_url
            return FakeUpstreamResponse(b'{"rates": {}}')

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            http_get(live_server, "/api/history?from=GBP&to=JPY&end=2026-07-03&days=7")

        assert "/2026-06-26..2026-07-03" in captured_url["url"]
        params = parse_qs(urlparse(captured_url["url"]).query)
        assert params == {"from": ["GBP"], "to": ["JPY"]}

    @pytest.mark.parametrize("days", ["0", "-5", "31", "99999", "abc"])
    def test_rejects_out_of_range_or_invalid_days(self, live_server, days):
        with patch("urllib.request.urlopen") as mock_urlopen:
            status, body, _ = http_get(
                live_server, f"/api/history?from=GBP&to=JPY&end=2026-07-03&days={days}"
            )

        mock_urlopen.assert_not_called()
        assert status == 400
        assert "error" in json.loads(body)

    def test_accepts_days_boundary_values(self, live_server):
        for days in (1, 30):
            with patch("urllib.request.urlopen", return_value=FakeUpstreamResponse(b'{"rates": {}}')):
                status, _, _ = http_get(
                    live_server, f"/api/history?from=GBP&to=JPY&end=2026-07-03&days={days}"
                )
            assert status == 200

    def test_rejects_malformed_end_date(self, live_server):
        with patch("urllib.request.urlopen") as mock_urlopen:
            status, _, _ = http_get(
                live_server, "/api/history?from=GBP&to=JPY&end=not-a-date&days=7"
            )

        mock_urlopen.assert_not_called()
        assert status == 400

    def test_rejects_invalid_currency_codes(self, live_server):
        with patch("urllib.request.urlopen") as mock_urlopen:
            status, _, _ = http_get(
                live_server, "/api/history?from=gbp&to=JPY&end=2026-07-03&days=7"
            )

        mock_urlopen.assert_not_called()
        assert status == 400


class TestStaticFileServing:
    def test_index_html_is_served(self, live_server):
        status, body, headers = http_get(live_server, "/index.html")

        assert status == 200
        assert "text/html" in headers.get("Content-Type", "")
        assert b"Currency Converter" in body

    def test_unknown_path_returns_404(self, live_server):
        status, _, _ = http_get(live_server, "/does-not-exist.html")

        assert status == 404
