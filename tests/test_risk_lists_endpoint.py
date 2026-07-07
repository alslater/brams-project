import json

from conftest import http_get, http_post_json


class TestGetRiskLists:
    def test_returns_current_lists(self, live_server):
        status, body, headers = http_get(live_server, "/risk-lists")

        assert status == 200
        assert headers.get("Content-Type") == "application/json"
        data = json.loads(body)
        assert data["sanctionedCountries"] == sorted(
            ["PRK", "IRN", "SYR", "CUB", "RUS", "BLR"]
        )
        assert "VEN" in data["watchlistCountries"]
        assert "john doe" in data["nameWatchlist"]


class TestReplaceRiskList:
    def test_replaces_sanctioned_countries_wholesale(self, live_server):
        status, body, _ = http_post_json(
            live_server,
            "/risk-lists",
            {"list": "sanctionedCountries", "values": ["irn", "prk"]},
        )

        assert status == 200
        data = json.loads(body)
        assert data["sanctionedCountries"] == ["IRN", "PRK"]

    def test_replace_can_remove_entries_by_omission(self, live_server):
        status, body, _ = http_post_json(
            live_server, "/risk-lists", {"list": "watchlistCountries", "values": ["AFG"]}
        )

        assert status == 200
        data = json.loads(body)
        assert data["watchlistCountries"] == ["AFG"]
        assert "VEN" not in data["watchlistCountries"]

    def test_replacing_with_empty_list_clears_it(self, live_server):
        status, body, _ = http_post_json(
            live_server, "/risk-lists", {"list": "watchlistCountries", "values": []}
        )

        assert status == 200
        assert json.loads(body)["watchlistCountries"] == []

    def test_name_watchlist_values_are_normalized_to_lowercase(self, live_server):
        status, body, _ = http_post_json(
            live_server,
            "/risk-lists",
            {"list": "nameWatchlist", "values": ["  Mallory Black  ", "Bob Vance"]},
        )

        assert status == 200
        data = json.loads(body)
        assert data["nameWatchlist"] == ["bob vance", "mallory black"]

    def test_replacing_one_list_does_not_affect_the_others(self, live_server):
        _, before_body, _ = http_get(live_server, "/risk-lists")
        before = json.loads(before_body)

        status, body, _ = http_post_json(
            live_server, "/risk-lists", {"list": "sanctionedCountries", "values": ["IRN"]}
        )

        data = json.loads(body)
        assert status == 200
        assert data["watchlistCountries"] == before["watchlistCountries"]
        assert data["nameWatchlist"] == before["nameWatchlist"]

    def test_replaced_sanctioned_list_actually_blocks_screening(self, live_server):
        payload = {
            "customerName": "Alice Wong",
            "nationality": "GBR",
            "amount": 100,
            "currency": "GBP",
            "destinationCountry": "FRA",
        }

        status, body, _ = http_post_json(live_server, "/screen", payload)
        assert json.loads(body)["outcome"] == "CLEAR"

        http_post_json(
            live_server, "/risk-lists", {"list": "sanctionedCountries", "values": ["FRA"]}
        )

        status, body, _ = http_post_json(live_server, "/screen", payload)
        data = json.loads(body)
        assert data["outcome"] == "BLOCKED"
        assert any("FRA" in reason for reason in data["reasons"])

    def test_omitting_a_previously_sanctioned_country_stops_blocking(self, live_server):
        payload = {
            "customerName": "Alice Wong",
            "nationality": "GBR",
            "amount": 100,
            "currency": "GBP",
            "destinationCountry": "IRN",
        }

        status, body, _ = http_post_json(live_server, "/screen", payload)
        assert json.loads(body)["outcome"] == "BLOCKED"

        # Replacing with a list that no longer includes IRN "removes" it.
        http_post_json(
            live_server, "/risk-lists", {"list": "sanctionedCountries", "values": ["PRK"]}
        )

        status, body, _ = http_post_json(live_server, "/screen", payload)
        assert json.loads(body)["outcome"] == "CLEAR"


class TestReplaceRiskListValidation:
    def test_rejects_unknown_list_name(self, live_server):
        status, body, _ = http_post_json(
            live_server, "/risk-lists", {"list": "notARealList", "values": ["IRN"]}
        )

        assert status == 400
        assert "error" in json.loads(body)

    def test_rejects_values_that_are_not_a_list(self, live_server):
        status, _, _ = http_post_json(
            live_server, "/risk-lists", {"list": "sanctionedCountries", "values": "IRN"}
        )

        assert status == 400

    def test_rejects_missing_values(self, live_server):
        status, _, _ = http_post_json(live_server, "/risk-lists", {"list": "sanctionedCountries"})

        assert status == 400

    def test_rejects_malformed_country_code(self, live_server):
        status, _, _ = http_post_json(
            live_server, "/risk-lists", {"list": "sanctionedCountries", "values": ["USA1"]}
        )

        assert status == 400

    def test_rejects_empty_string_entry(self, live_server):
        status, _, _ = http_post_json(
            live_server, "/risk-lists", {"list": "nameWatchlist", "values": ["   "]}
        )

        assert status == 400

    def test_rejects_non_string_entry(self, live_server):
        status, _, _ = http_post_json(
            live_server, "/risk-lists", {"list": "nameWatchlist", "values": [123]}
        )

        assert status == 400

    def test_rejects_oversized_name_entry(self, live_server):
        status, _, _ = http_post_json(
            live_server, "/risk-lists", {"list": "nameWatchlist", "values": ["A" * 201]}
        )

        assert status == 400

    def test_rejects_too_many_entries(self, live_server):
        status, _, _ = http_post_json(
            live_server,
            "/risk-lists",
            {"list": "nameWatchlist", "values": [f"name {i}" for i in range(201)]},
        )

        assert status == 400

    def test_rejects_non_dict_payload(self, live_server):
        status, _, _ = http_post_json(live_server, "/risk-lists", ["not", "a", "dict"])

        assert status == 400

    def test_rejected_update_does_not_change_existing_lists(self, live_server):
        _, before_body, _ = http_get(live_server, "/risk-lists")
        before = json.loads(before_body)

        status, _, _ = http_post_json(
            live_server, "/risk-lists", {"list": "sanctionedCountries", "values": ["XX"]}
        )
        assert status == 400

        _, after_body, _ = http_get(live_server, "/risk-lists")
        assert json.loads(after_body) == before
