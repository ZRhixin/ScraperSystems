"""
HTTP handler for n8n integration.
POST http://your-host:8001
Body: {
    "first_name": "James",
    "last_name": "Smith",
    "middle_name": "",
    "street_address": "",
    "city": "Miami",
    "state": "Florida",
    "zip_code": ""
}
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from .client import lookup

_lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid JSON"})
            return

        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        state = (data.get("state") or "").strip()
        zip_code = (data.get("zip_code") or "").strip()

        if not state and not zip_code:
            self._respond(400, {"error": "at least state or zip_code is required"})
            return

        try:
            with _lock:
                result = lookup(
                    first_name=first_name,
                    last_name=last_name,
                    middle_name=(data.get("middle_name") or "").strip(),
                    street_address=(data.get("street_address") or "").strip(),
                    city=(data.get("city") or "").strip(),
                    state=(data.get("state") or "").strip(),
                    zip_code=(data.get("zip_code") or "").strip(),
                )
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
    port = port or int(os.getenv("SKIPGENIE_PORT", 8001))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    print(f"[SkipGenie] Listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
