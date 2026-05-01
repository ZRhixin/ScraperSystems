"""
HTTP handler for Mecklenburg County Assessor — n8n integration.
POST http://your-host:8004

Search properties:
  {"search_type": "search", "term": "Bowes"}
  {"search_type": "search", "term": "210 N Church St"}
  {"search_type": "search", "term": "07848416"}

Get owner suggestions only:
  {"search_type": "suggestions", "term": "Bowes"}
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from .search import search, suggestions

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

        search_type = (data.get("search_type") or "search").strip().lower()
        term = (data.get("term") or "").strip()

        if not term:
            self._respond(400, {"error": "term is required"})
            return

        try:
            with _lock:
                if search_type == "suggestions":
                    result = suggestions(term)
                elif search_type == "search":
                    result = search(term)
                else:
                    self._respond(400, {"error": "search_type must be: search or suggestions"})
                    return

            self._respond(200, {"count": len(result), "results": result})

        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def do_GET(self):
        self._respond(200, {"status": "ok", "service": "mecklenburg-assessor"})

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
    port = port or int(os.getenv("MECKLENBURG_PORT", 8004))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    print(f"[Mecklenburg Assessor] Listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
