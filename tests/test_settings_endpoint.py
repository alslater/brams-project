import json

from conftest import http_get, http_post_json


class TestGetSettings:
    def test_returns_current_defaults(self, live_server):
        status, body, headers = http_get(live_server, "/settings")

        assert status == 200
        assert headers.get("Content-Type") == "application/json"
        data = json.loads(body)
        assert data == {"highValueThreshold": 5000, "nameSimilarityThreshold": 0.85}


class TestUpdateSettings:
    def test_updates_high_value_threshold(self, live_server):
        status, body, _ = http_post_json(live_server, "/settings", {"highValueThreshold": 20000})

        assert status == 200
        data = json.loads(body)
        assert data["highValueThreshold"] == 20000
        assert data["nameSimilarityThreshold"] == 0.85

    def test_updates_similarity_threshold(self, live_server):
        status, body, _ = http_post_json(
            live_server, "/settings", {"nameSimilarityThreshold": 0.95}
        )

        assert status == 200
        data = json.loads(body)
        assert data["nameSimilarityThreshold"] == 0.95
        assert data["highValueThreshold"] == 5000

    def test_updates_both_at_once(self, live_server):
        status, body, _ = http_post_json(
            live_server,
            "/settings",
            {"highValueThreshold": 10000, "nameSimilarityThreshold": 0.9},
        )

        data = json.loads(body)
        assert status == 200
        assert data == {"highValueThreshold": 10000, "nameSimilarityThreshold": 0.9}

    def test_get_reflects_previous_update(self, live_server):
        http_post_json(live_server, "/settings", {"highValueThreshold": 12345})
        status, body, _ = http_get(live_server, "/settings")

        assert status == 200
        assert json.loads(body)["highValueThreshold"] == 12345

    def test_updated_threshold_changes_screen_outcome(self, live_server):
        payload = {
            "customerName": "Alice Wong",
            "nationality": "GBR",
            "amount": 6000,
            "currency": "GBP",
            "destinationCountry": "DEU",
        }

        # Above the default £5,000 threshold -> REVIEW.
        status, body, _ = http_post_json(live_server, "/screen", payload)
        assert json.loads(body)["outcome"] == "REVIEW"

        # Raise the threshold so the same transaction now clears.
        http_post_json(live_server, "/settings", {"highValueThreshold": 10000})
        status, body, _ = http_post_json(live_server, "/screen", payload)
        assert json.loads(body)["outcome"] == "CLEAR"

    def test_raised_similarity_threshold_stops_fuzzy_match(self, live_server):
        payload = {
            "customerName": "Jon Doe",  # ~93% similar to watchlisted "John Doe"
            "nationality": "GBR",
            "amount": 100,
            "currency": "GBP",
            "destinationCountry": "DEU",
        }

        status, body, _ = http_post_json(live_server, "/screen", payload)
        assert json.loads(body)["outcome"] == "REVIEW"

        # Raise the bar above the ~93% match so it's no longer flagged.
        http_post_json(live_server, "/settings", {"nameSimilarityThreshold": 0.99})
        status, body, _ = http_post_json(live_server, "/screen", payload)
        assert json.loads(body)["outcome"] == "CLEAR"


class TestUpdateSettingsValidation:
    def test_rejects_threshold_below_minimum(self, live_server):
        status, body, _ = http_post_json(live_server, "/settings", {"highValueThreshold": 0})

        assert status == 400
        assert "error" in json.loads(body)

    def test_rejects_threshold_above_maximum(self, live_server):
        status, _, _ = http_post_json(
            live_server, "/settings", {"highValueThreshold": 10_000_000}
        )

        assert status == 400

    def test_rejects_negative_threshold(self, live_server):
        status, _, _ = http_post_json(live_server, "/settings", {"highValueThreshold": -100})

        assert status == 400

    def test_rejects_non_numeric_threshold(self, live_server):
        status, _, _ = http_post_json(live_server, "/settings", {"highValueThreshold": "lots"})

        assert status == 400

    def test_rejects_boolean_threshold(self, live_server):
        # bool is a subclass of int in Python — must not be silently accepted as a number.
        status, _, _ = http_post_json(live_server, "/settings", {"highValueThreshold": True})

        assert status == 400

    def test_rejects_similarity_below_minimum(self, live_server):
        status, _, _ = http_post_json(
            live_server, "/settings", {"nameSimilarityThreshold": 0.1}
        )

        assert status == 400

    def test_rejects_similarity_above_maximum(self, live_server):
        status, _, _ = http_post_json(
            live_server, "/settings", {"nameSimilarityThreshold": 1.5}
        )

        assert status == 400

    def test_rejects_empty_payload(self, live_server):
        status, body, _ = http_post_json(live_server, "/settings", {})

        assert status == 400
        assert "error" in json.loads(body)

    def test_rejects_non_dict_payload(self, live_server):
        status, _, _ = http_post_json(live_server, "/settings", [1, 2, 3])

        assert status == 400

    def test_a_rejected_update_does_not_change_existing_settings(self, live_server):
        http_post_json(live_server, "/settings", {"highValueThreshold": 7000})
        status, _, _ = http_post_json(live_server, "/settings", {"highValueThreshold": -1})
        assert status == 400

        _, body, _ = http_get(live_server, "/settings")
        assert json.loads(body)["highValueThreshold"] == 7000
