#!/usr/bin/env python3
import datetime
import json
import urllib.request
import urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

FRANKFURTER_ROOT = "https://api.frankfurter.app"
FRANKFURTER_BASE = f"{FRANKFURTER_ROOT}/latest"


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

        upstream_url = f"{FRANKFURTER_BASE}?amount={amount}&from={base}&to={to}"
        self.proxy_json(upstream_url)

    def handle_history(self, query):
        base = query.get("from", ["USD"])[0]
        to = query.get("to", [""])[0]
        end = query.get("end", [""])[0]
        days = query.get("days", ["10"])[0]

        try:
            end_date = datetime.date.fromisoformat(end)
            start_date = end_date - datetime.timedelta(days=int(days))
        except ValueError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "invalid end/days parameter"}).encode())
            return

        upstream_url = (
            f"{FRANKFURTER_ROOT}/{start_date.isoformat()}..{end_date.isoformat()}"
            f"?from={base}&to={to}"
        )
        self.proxy_json(upstream_url)

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
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        pass


def main():
    port = 8765
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Serving on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
