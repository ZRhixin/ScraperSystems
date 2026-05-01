"""
HTTP handler for New Hanover County Assessor — n8n integration.
POST http://your-host:8006

Search by address:
  {"search_type": "address", "street_name": "Asheville", "street_number": "6"}
  {"search_type": "address", "street_name": "Asheville", "direction": "E"}

Search by owner:
  {"search_type": "owner", "owner_name": "Smith"}

Search by parcel ID:
  {"search_type": "parcel", "parcel_id": "R05720-031-010-000"}

Optional for all: "page" (int, default 1), "page_size" (int, default 25)
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from .search import search_by_address, search_by_owner, search_by_parcel

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
        page = int(data.get("page") or 1)
        page_size = int(data.get("page_size") or 25)

        try:
            with _lock:
                if search_type == "address":
                    street_name = (data.get("street_name") or "").strip()
                    if not street_name:
                        self._respond(400, {"error": "street_name is required for address search"})
                        return
                    result = search_by_address(
                        street_name=street_name,
                        street_number=(data.get("street_number") or "").strip(),
                        suffix=(data.get("suffix") or "***").strip(),
                        direction=(data.get("direction") or "").strip(),
                        page=page,
                        page_size=page_size,
                    )

                elif search_type == "owner":
                    owner_name = (data.get("owner_name") or "").strip()
                    if not owner_name:
                        self._respond(400, {"error": "owner_name is required for owner search"})
                        return
                    result = search_by_owner(owner_name, page=page, page_size=page_size)

                elif search_type == "parcel":
                    parcel_id = (data.get("parcel_id") or "").strip()
                    if not parcel_id:
                        self._respond(400, {"error": "parcel_id is required for parcel search"})
                        return
                    result = search_by_parcel(parcel_id, page=page, page_size=page_size)

                else:
                    self._respond(400, {"error": "search_type must be: address, owner, or parcel"})
                    return

            self._respond(200, {"count": len(result), "results": result})

        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def do_GET(self):
        self._respond(200, {"status": "ok", "service": "newhanover-assessor"})

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
    port = port or int(os.getenv("NEWHANOVER_PORT", 8006))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    print(f"[New Hanover Assessor] Listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
