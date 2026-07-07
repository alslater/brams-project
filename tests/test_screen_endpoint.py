import json
from unittest.mock import patch

from conftest import FakeUpstreamResponse, http_get, http_post_json

VALID_PAYLOAD = {
    "customerName": "Alice Wong",
    "nationality": "GBR",
    "amount": 100,
    "currency": "GBP",
    "destinationCountry": "DEU",
}


def payload(**overrides):
    return {**VALID_PAYLOAD, **overrides}


class TestScreenOutcomes:
    def test_clear_case_needs_no_network_call(self, live_server):
        with patch("urllib.request.urlopen") as mock_urlopen:
            status, body, headers = http_post_json(live_server, "/screen", payload())

        mock_urlopen.assert_not_called()
        assert status == 200
        assert headers.get("Content-Type") == "application/json"
        data = json.loads(body)
        assert data == {"outcome": "CLEAR", "reasons": ["No risk indicators identified."]}

    def test_sanctioned_destination_country_is_blocked(self, live_server):
        status, body, _ = http_post_json(live_server, "/screen", payload(destinationCountry="IRN"))

        assert status == 200
        data = json.loads(body)
        assert data["outcome"] == "BLOCKED"
        assert any("IRN" in reason for reason in data["reasons"])

    def test_sanctioned_nationality_is_blocked(self, live_server):
        status, body, _ = http_post_json(live_server, "/screen", payload(nationality="RUS"))

        data = json.loads(body)
        assert status == 200
        assert data["outcome"] == "BLOCKED"
        assert any("RUS" in reason for reason in data["reasons"])

    def test_exact_name_watchlist_match_is_blocked(self, live_server):
        status, body, _ = http_post_json(live_server, "/screen", payload(customerName="John Doe"))

        data = json.loads(body)
        assert status == 200
        assert data["outcome"] == "BLOCKED"
        assert any("watch list" in reason for reason in data["reasons"])

    def test_similar_name_is_flagged_for_review_not_blocked(self, live_server):
        # "Jon Doe" is a near-miss (~93% similarity) for the watchlisted "John Doe" —
        # not a confirmed match, so it should escalate to REVIEW rather than BLOCKED.
        status, body, _ = http_post_json(live_server, "/screen", payload(customerName="Jon Doe"))

        data = json.loads(body)
        assert status == 200
        assert data["outcome"] == "REVIEW"
        assert any("similar to watch list entry" in reason for reason in data["reasons"])

    def test_watchlist_destination_country_is_review(self, live_server):
        status, body, _ = http_post_json(live_server, "/screen", payload(destinationCountry="VEN"))

        data = json.loads(body)
        assert status == 200
        assert data["outcome"] == "REVIEW"
        assert any("VEN" in reason for reason in data["reasons"])

    def test_high_value_gbp_amount_is_review(self, live_server):
        status, body, _ = http_post_json(
            live_server, "/screen", payload(amount=5500, currency="GBP")
        )

        data = json.loads(body)
        assert status == 200
        assert data["outcome"] == "REVIEW"
        assert any("5,500.00 GBP exceeds" in reason for reason in data["reasons"])

    def test_high_value_amount_after_currency_conversion_is_review(self, live_server):
        upstream_body = json.dumps(
            {"amount": 6000.0, "base": "USD", "date": "2026-07-03", "rates": {"GBP": 6600.0}}
        ).encode()

        with patch("urllib.request.urlopen", return_value=FakeUpstreamResponse(upstream_body)):
            status, body, _ = http_post_json(
                live_server, "/screen", payload(amount=6000, currency="USD")
            )

        data = json.loads(body)
        assert status == 200
        assert data["outcome"] == "REVIEW"
        assert any("6,600.00 GBP" in reason for reason in data["reasons"])

    def test_conversion_failure_fails_safe_to_review(self, live_server):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            status, body, _ = http_post_json(
                live_server, "/screen", payload(amount=100, currency="USD")
            )

        data = json.loads(body)
        assert status == 200
        assert data["outcome"] == "REVIEW"
        assert any("conversion unavailable" in reason for reason in data["reasons"])
        # The raw exception text must never reach the client.
        assert "timed out" not in body.decode()

    def test_blocked_outcome_includes_review_reasons_too(self, live_server):
        # A sanctioned destination (BLOCKED) alongside a high-value amount (REVIEW)
        # should still surface both reasons, with BLOCKED as the overall outcome.
        status, body, _ = http_post_json(
            live_server, "/screen", payload(destinationCountry="IRN", amount=5500, currency="GBP")
        )

        data = json.loads(body)
        assert status == 200
        assert data["outcome"] == "BLOCKED"
        assert len(data["reasons"]) == 2


class TestScreenValidation:
    def test_missing_required_field_returns_400(self, live_server):
        status, body, _ = http_post_json(live_server, "/screen", payload(customerName=""))

        assert status == 400
        assert "error" in json.loads(body)

    def test_invalid_currency_returns_400(self, live_server):
        status, _, _ = http_post_json(live_server, "/screen", payload(currency="XXXX"))

        assert status == 400

    def test_invalid_country_code_format_returns_400(self, live_server):
        status, _, _ = http_post_json(live_server, "/screen", payload(nationality="UK"))

        assert status == 400

    def test_negative_amount_returns_400(self, live_server):
        status, _, _ = http_post_json(live_server, "/screen", payload(amount=-5))

        assert status == 400

    def test_non_numeric_amount_returns_400(self, live_server):
        status, _, _ = http_post_json(live_server, "/screen", payload(amount="abc"))

        assert status == 400

    def test_oversized_customer_name_returns_400(self, live_server):
        status, _, _ = http_post_json(live_server, "/screen", payload(customerName="A" * 201))

        assert status == 400

    def test_oversized_request_body_returns_400(self, live_server):
        status, _, _ = http_post_json(
            live_server, "/screen", payload(customerName="A" * 20_000)
        )

        assert status == 400

    def test_non_dict_json_body_returns_400(self, live_server):
        status, _, _ = http_post_json(live_server, "/screen", ["not", "a", "dict"])

        assert status == 400

    def test_get_on_screen_is_not_routed(self, live_server):
        status, _, _ = http_get(live_server, "/screen")

        assert status == 404
