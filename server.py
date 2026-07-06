#!/usr/bin/env python3
import datetime
import json
import re
import sys
import urllib.request
import urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode

FRANKFURTER_ROOT = "https://api.frankfurter.app"
FRANKFURTER_BASE = f"{FRANKFURTER_ROOT}/latest"

CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")
AMOUNT_RE = re.compile(r"^\d+(\.\d+)?$")
MAX_CURRENCY_CODES = 15


def is_valid_currency_code(code):
    return bool(CURRENCY_CODE_RE.match(code))


def is_valid_currency_list(value):
    if not value:
        return False
    codes = value.split(",")
    if len(codes) > MAX_CURRENCY_CODES:
        return False
    return all(is_valid_currency_code(code) for code in codes)


def is_valid_amount(value):
    return bool(AMOUNT_RE.match(value))


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
