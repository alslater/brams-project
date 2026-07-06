#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

FRANKFURTER_BASE = "https://api.frankfurter.app/latest"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/convert":
            self.handle_convert(parse_qs(parsed.query))
            return

        super().do_GET()

    def handle_convert(self, query):
        amount = query.get("amount", ["1"])[0]
        base = query.get("from", ["USD"])[0]
        to = query.get("to", [""])[0]

        upstream_url = f"{FRANKFURTER_BASE}?amount={amount}&from={base}&to={to}"

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
