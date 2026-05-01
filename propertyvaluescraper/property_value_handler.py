import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from .property_value_scraper import scrape_all


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid JSON"})
            return

        address = (data.get("address") or "").strip()
        if not address:
            self._respond(400, {"error": "address is required"})
            return

        try:
            result = asyncio.run(scrape_all(address))
            self._respond(200, result)
        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def do_GET(self):
        self._respond(200, {"status": "ok"})

    def _respond(self, status: int, data: dict):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def run(port: int | None = None):
    port = port or int(os.getenv("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    print(f"Listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
