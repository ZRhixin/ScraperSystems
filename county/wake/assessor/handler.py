"""
HTTP handler for Wake County Assessor — n8n integration.
POST http://your-host:8002

Search by owner:
  {"search_type": "owner", "last_name": "Smith", "first_name": "John", "fetch_details": false}

Search by address:
  {"search_type": "address", "street_name": "Valleyfield", "street_number": "6101", "fetch_details": false}

Search by Real Estate ID:
  {"search_type": "id", "real_estate_id": "0103838", "fetch_details": true}

Search by PIN:
  {"search_type": "pin", "map": "0796", "sheet": "", "block": "", "lot": ""}

GET account detail directly:
  {"search_type": "account", "account_id": "0103838"}
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from .search import (
    get_account,
    search_by_address,
    search_by_id,
    search_by_owner,
    search_by_pin,
)

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
        fetch_details = bool(data.get("fetch_details", False))

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
                        fetch_details=fetch_details,
                    )

                elif search_type == "address":
                    street_name = (data.get("street_name") or "").strip()
                    if not street_name:
                        self._respond(400, {"error": "street_name is required"})
                        return
                    result = search_by_address(
                        street_name=street_name,
                        street_number=(data.get("street_number") or "").strip(),
                        fetch_details=fetch_details,
                    )

                elif search_type == "id":
                    real_estate_id = (data.get("real_estate_id") or "").strip()
                    if not real_estate_id:
                        self._respond(400, {"error": "real_estate_id is required"})
                        return
                    result = search_by_id(real_estate_id, fetch_details=fetch_details)

                elif search_type == "pin":
                    map_num = (data.get("map") or "").strip()
                    if not map_num:
                        self._respond(400, {"error": "map is required for PIN search"})
                        return
                    result = search_by_pin(
                        map_num=map_num,
                        sheet=(data.get("sheet") or "").strip(),
                        block=(data.get("block") or "").strip(),
                        lot=(data.get("lot") or "").strip(),
                        fetch_details=fetch_details,
                    )

                elif search_type == "account":
                    account_id = (data.get("account_id") or "").strip()
                    if not account_id:
                        self._respond(400, {"error": "account_id is required"})
                        return
                    result = get_account(account_id)

                else:
                    self._respond(400, {"error": "search_type must be one of: owner, address, id, pin, account"})
                    return

            self._respond(200, {"results": result} if isinstance(result, list) else result)

        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def do_GET(self):
        self._respond(200, {"status": "ok", "service": "wake-county-assessor"})

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
    port = port or int(os.getenv("WAKECOUNTY_PORT", 8002))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    print(f"[WakeCounty] Listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
