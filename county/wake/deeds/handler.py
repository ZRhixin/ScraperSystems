"""
HTTP handler for Wake County Register of Deeds — n8n integration.
POST http://your-host:8007

Search by name (grantor, grantee, or both):
  {"search_type": "name", "surname": "Bowes"}
  {"search_type": "name", "surname": "Bowes", "first_name": "Elizabeth", "role": "grantee"}
  {"search_type": "name", "surname": "Smith", "role": "grantor", "doc_types": ["DEED", "QUIT CLAIM DEED"]}
  {"search_type": "name", "surname": "Bowes", "start_date": "01/01/2000", "end_date": "12/31/2020"}

Search by document number:
  {"search_type": "document", "document_number": "004714-00624"}

Fetch full detail for a known document ID:
  {"search_type": "detail", "doc_id": "DOCC554325"}

Optional for name/document: "fetch_details": true, "page": 1 (0 = all pages)
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from .search import get_document, search_by_document, search_by_name

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
        page = int(data.get("page") or 1)

        try:
            with _lock:
                if search_type == "name":
                    surname = (data.get("surname") or "").strip()
                    if not surname:
                        self._respond(400, {"error": "surname is required for name search"})
                        return
                    result = search_by_name(
                        surname=surname,
                        first_name=(data.get("first_name") or "").strip(),
                        role=(data.get("role") or "both").strip().lower(),
                        start_date=(data.get("start_date") or "").strip(),
                        end_date=(data.get("end_date") or "").strip(),
                        doc_types=data.get("doc_types") or None,
                        page=page,
                        fetch_details=fetch_details,
                    )

                elif search_type == "document":
                    doc_number = (data.get("document_number") or "").strip()
                    if not doc_number:
                        self._respond(400, {"error": "document_number is required"})
                        return
                    result = search_by_document(doc_number, fetch_details=fetch_details)

                elif search_type == "detail":
                    doc_id = (data.get("doc_id") or "").strip()
                    if not doc_id:
                        self._respond(400, {"error": "doc_id is required"})
                        return
                    detail = get_document(None, doc_id)
                    self._respond(200, {"count": 1, "results": [detail]})
                    return

                else:
                    self._respond(400, {"error": "search_type must be: name, document, or detail"})
                    return

            self._respond(200, {"count": len(result), "results": result})

        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def do_GET(self):
        self._respond(200, {"status": "ok", "service": "wakecounty-deeds"})

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
    port = port or int(os.getenv("WAKECOUNTY_DEEDS_PORT", 8007))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    print(f"[Wake County Deeds] Listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
