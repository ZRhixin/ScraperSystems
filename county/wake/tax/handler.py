"""
HTTP handler for Wake County Property Tax — n8n integration.
POST http://your-host:8003

Search by owner:
  {"search_type": "owner", "last_name": "Smith", "first_name": "John", "middle_name": "", "years": 10, "all_pages": false}

Search by account number:
  {"search_type": "account", "account_number": "0000073365", "years": 10}

Search by business name:
  {"search_type": "business", "business_name": "Acme Corp", "years": 10}
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from .search import search_by_owner

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

        search_type = (data.get("search_type") or "").strip().lower()
        years = int(data.get("years", 10))
        all_pages = bool(data.get("all_pages", False))

        try:
            with _lock:
                if search_type == "owner":
                    last_name = (data.get("last_name") or "").strip()
                    if not last_name:
                        self._respond(400, {"error": "last_name is required"})
                        return
                    result = search_by_owner(
                        last_name=last_name,
                        first_name=(data.get("first_name") or "").strip(),
                        middle_name=(data.get("middle_name") or "").strip(),
                        years=years,
                        all_pages=all_pages,
                    )

                elif search_type in ("account", "business"):
                    self._respond(501, {"error": f"{search_type} search is not yet verified — use owner search"})
                    return

                else:
                    self._respond(400, {"error": "search_type must be: owner"})
                    return

            self._respond(200, {"count": len(result), "results": result})

        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def do_GET(self):
        self._respond(200, {"status": "ok", "service": "wake-county-tax"})

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
    port = port or int(os.getenv("WAKECOUNTY_TAX_PORT", 8003))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    print(f"[WakeCounty Tax] Listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
