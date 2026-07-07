#!/usr/bin/env python3
import datetime
import difflib
import json
import math
import re
import sys
import urllib.request
import urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode

FRANKFURTER_ROOT = "https://api.frankfurter.app"
FRANKFURTER_BASE = f"{FRANKFURTER_ROOT}/latest"

ALPHA3_CODE_RE = re.compile(r"^[A-Z]{3}$")
AMOUNT_RE = re.compile(r"^\d+(\.\d+)?$")
MAX_CURRENCY_CODES = 15


def is_valid_currency_code(code):
    return bool(ALPHA3_CODE_RE.match(code))


def is_valid_country_code(code):
    """Validates an ISO 3166-1 alpha-3 country code, e.g. GBR, USA, IRN."""
    return bool(ALPHA3_CODE_RE.match(code))


def is_valid_currency_list(value):
    if not value:
        return False
    codes = value.split(",")
    if len(codes) > MAX_CURRENCY_CODES:
        return False
    return all(is_valid_currency_code(code) for code in codes)


def is_valid_amount(value):
    return bool(AMOUNT_RE.match(value))


# Demo-only mock data. These are illustrative placeholder lists, not a real
# sanctions/watchlist data source, and exist purely to make the screening
# rule engine below produce varied, testable outcomes. Countries are
# identified by their ISO 3166-1 alpha-3 code (e.g. GBR, USA, IRN).
SANCTIONED_COUNTRIES = {"PRK", "IRN", "SYR", "CUB", "RUS", "BLR"}
WATCHLIST_COUNTRIES = {"AFG", "MMR", "VEN", "YEM"}
NAME_WATCHLIST = {
    "john doe",
    "jane smith",
    "viktor petrov",
    "anna kozlov",
    "hassan rahimi",
    "carlos fuentes-vega",
    "li wei chen",
    "olga morozova",
    "ahmed al-rashid",
    "dimitri volkov",
    "fatima al-zahra",
    "boris yanovich",
}

# Below 1.0 (exact match), a name is flagged as merely "similar" to a watch
# list entry — e.g. a typo, transliteration, or partial match — and sent to
# REVIEW rather than auto-blocked, since it isn't a confirmed match.
NAME_SIMILARITY_THRESHOLD = 0.85


def find_name_watchlist_match(name_norm):
    """Returns (matched_name, ratio) for the closest NAME_WATCHLIST entry if
    it meets NAME_SIMILARITY_THRESHOLD, else None. ratio == 1.0 means an
    exact match.
    """
    best_match = None
    best_ratio = 0.0
    for watchlist_name in NAME_WATCHLIST:
        ratio = difflib.SequenceMatcher(None, name_norm, watchlist_name).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = watchlist_name

    if best_match is not None and best_ratio >= NAME_SIMILARITY_THRESHOLD:
        return best_match, best_ratio
    return None


# The high-value threshold is denominated in the local currency: every
# transaction is screened on its GBP equivalent, regardless of the currency
# it was submitted in, so a foreign-currency amount can't dodge the check.
# Exceeding this threshold always escalates the result to at least REVIEW.
LOCAL_CURRENCY = "GBP"
HIGH_VALUE_THRESHOLD = 5000
MAX_TEXT_FIELD_LENGTH = 200
MAX_SCREEN_BODY_BYTES = 10_000


def convert_to_local_currency(amount, currency):
    """Converts `amount` in `currency` to LOCAL_CURRENCY using live rates.

    Returns None if the live conversion could not be performed, so callers
    can fail safe instead of silently skipping the threshold check.
    """
    if currency == LOCAL_CURRENCY:
        return amount

    upstream_url = f"{FRANKFURTER_BASE}?{urlencode({'amount': amount, 'from': currency, 'to': LOCAL_CURRENCY})}"
    req = urllib.request.Request(
        upstream_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; currency-converter-proxy/1.0)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data["rates"][LOCAL_CURRENCY]
    except Exception as e:
        print(f"convert_to_local_currency failed for {amount} {currency}: {e}", file=sys.stderr)
        return None


def screen_transaction(customer_name, nationality, amount, currency, destination_country, gbp_amount):
    blocked_reasons = []
    review_reasons = []

    destination_code = destination_country.strip().upper()
    nationality_code = nationality.strip().upper()
    name_norm = customer_name.strip().lower()

    if destination_code in SANCTIONED_COUNTRIES:
        blocked_reasons.append(
            f"Destination country '{destination_code}' is on the sanctions list."
        )

    if nationality_code in SANCTIONED_COUNTRIES:
        blocked_reasons.append(
            f"Customer nationality '{nationality_code}' is on the sanctions list."
        )

    name_match = find_name_watchlist_match(name_norm)
    if name_match:
        matched_name, ratio = name_match
        if ratio >= 1.0:
            blocked_reasons.append("Customer name matches an entry on the watch list.")
        else:
            review_reasons.append(
                f"Customer name is similar to watch list entry '{matched_name.title()}' "
                f"({ratio:.0%} match) and requires manual review."
            )

    if destination_code in WATCHLIST_COUNTRIES:
        review_reasons.append(
            f"Destination country '{destination_code}' is flagged as high-risk."
        )

    if gbp_amount is None:
        review_reasons.append(
            "Unable to verify the GBP-equivalent amount for threshold screening "
            "(currency conversion unavailable)."
        )
    elif gbp_amount > HIGH_VALUE_THRESHOLD:
        if currency == LOCAL_CURRENCY:
            review_reasons.append(
                f"Transaction amount of {amount:,.2f} {currency} exceeds the "
                f"{HIGH_VALUE_THRESHOLD:,} {LOCAL_CURRENCY} review threshold."
            )
        else:
            review_reasons.append(
                f"Transaction amount of {amount:,.2f} {currency} (~{gbp_amount:,.2f} {LOCAL_CURRENCY}) "
                f"exceeds the {HIGH_VALUE_THRESHOLD:,} {LOCAL_CURRENCY} review threshold."
            )

    if blocked_reasons:
        return "BLOCKED", blocked_reasons + review_reasons
    if review_reasons:
        return "REVIEW", review_reasons
    return "CLEAR", ["No risk indicators identified."]


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/convert":
            self.handle_convert(parse_qs(parsed.query))
            return

        if parsed.path == "/api/history":
            self.handle_history(parse_qs(parsed.query))
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/screen":
            self.handle_screen()
            return

        self.send_json_error(404, "not found")

    def handle_screen(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0 or length > MAX_SCREEN_BODY_BYTES:
            self.send_json_error(400, "invalid request body")
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_json_error(400, "invalid JSON body")
            return

        if not isinstance(payload, dict):
            self.send_json_error(400, "invalid request body")
            return

        customer_name = str(payload.get("customerName", "")).strip()
        nationality = str(payload.get("nationality", "")).strip().upper()
        destination_country = str(payload.get("destinationCountry", "")).strip().upper()
        currency = str(payload.get("currency", "")).strip().upper()
        amount_raw = payload.get("amount")

        if not customer_name or not nationality or not destination_country:
            self.send_json_error(400, "customerName, nationality, and destinationCountry are required")
            return

        if len(customer_name) > MAX_TEXT_FIELD_LENGTH:
            self.send_json_error(400, "field exceeds maximum length")
            return

        if not is_valid_currency_code(currency):
            self.send_json_error(400, "invalid currency")
            return

        if not (is_valid_country_code(nationality) and is_valid_country_code(destination_country)):
            self.send_json_error(400, "nationality and destinationCountry must be 3-letter ISO country codes")
            return

        try:
            amount = float(amount_raw)
        except (TypeError, ValueError):
            self.send_json_error(400, "invalid amount")
            return

        if amount < 0 or not math.isfinite(amount):
            self.send_json_error(400, "invalid amount")
            return

        gbp_amount = convert_to_local_currency(amount, currency)

        outcome, reasons = screen_transaction(
            customer_name, nationality, amount, currency, destination_country, gbp_amount
        )

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"outcome": outcome, "reasons": reasons}).encode())

    def handle_convert(self, query):
        amount = query.get("amount", ["1"])[0]
        base = query.get("from", ["USD"])[0]
        to = query.get("to", [""])[0]

        if not (is_valid_amount(amount) and is_valid_currency_code(base) and is_valid_currency_list(to)):
            self.send_json_error(400, "invalid amount/from/to parameter")
            return

        upstream_url = f"{FRANKFURTER_BASE}?{urlencode({'amount': amount, 'from': base, 'to': to})}"
        self.proxy_json(upstream_url)

    def handle_history(self, query):
        base = query.get("from", ["USD"])[0]
        to = query.get("to", [""])[0]
        end = query.get("end", [""])[0]
        days = query.get("days", ["10"])[0]

        if not (is_valid_currency_code(base) and is_valid_currency_list(to)):
            self.send_json_error(400, "invalid from/to parameter")
            return

        try:
            end_date = datetime.date.fromisoformat(end)
            days_int = int(days)
            if not 1 <= days_int <= 30:
                raise ValueError("days out of range")
            start_date = end_date - datetime.timedelta(days=days_int)
        except ValueError:
            self.send_json_error(400, "invalid end/days parameter")
            return

        date_range = f"{start_date.isoformat()}..{end_date.isoformat()}"
        upstream_url = f"{FRANKFURTER_ROOT}/{date_range}?{urlencode({'from': base, 'to': to})}"
        self.proxy_json(upstream_url)

    def send_json_error(self, code, message):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": message}).encode())

    def proxy_json(self, upstream_url):
        req = urllib.request.Request(
            upstream_url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; currency-converter-proxy/1.0)"},
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            print(f"proxy_json failed for {upstream_url}: {e}", file=sys.stderr)
            self.send_json_error(502, "upstream request failed")

    def log_message(self, format, *args):
        pass


def main():
    port = 8765
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
