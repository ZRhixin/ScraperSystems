"""
Unified scraper server — single port, routes by path.
Designed for n8n and realestate backend integration.

Usage:
    python server.py

Routes:
    POST /county/wake/assessor    — search_type: owner, address, id, pin, account
    POST /county/wake/deeds       — search_type: name, document, detail
    POST /county/mecklenburg/assessor   — search_type: search, suggestions
    POST /county/newhanover/assessor    — search_type: address, owner, parcel
    POST /county/buncombe/assessor      — search_type: search, suggestions
    POST /skipgenie                     — first_name, last_name, state or zip_code
    POST /court/nc/search               — name (party name search, statewide)
    POST /court/nc/register_of_actions  — case_url (Register of Actions for one case)
    POST /investigate/pull-deed         — property_id, book, page → capture_id (Wake ROD combined)
    POST /conclude/data                 — property_id → all DB data for Prompt 4
    POST /conclude/write                — property_id + Prompt 4 output → chain_conclusions row
    POST /verify/data                   — conclusion_id → conclusion + referenced extractions
    POST /verify/write                  — conclusion_id + verdict → updates chain_conclusions
    GET  /                              — health check + route list
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from county.wake.assessor.search import (
    get_account,
    search_by_address as wc_assessor_address,
    search_by_id,
    search_by_owner as wc_assessor_owner,
    search_by_pin,
)
from county.wake.deeds.search import (
    get_document,
    search_by_document,
    search_by_name as wc_deeds_name,
    search_by_book_page as wc_deeds_book_page,
    download_document_pdf as wc_deeds_download_pdf,
)
from county.mecklenburg.assessor.search import search as meck_search, suggestions as meck_suggestions
from county.newhanover.assessor.search import (
    search_by_address as nh_address,
    search_by_owner as nh_owner,
    search_by_parcel as nh_parcel,
)
from county.buncombe.assessor.search import search as bunc_search, suggestions as bunc_suggestions
from skipgenieapi.client import lookup as skipgenie_lookup
from court.nc.search import (
    search_by_name as nc_court_search,
    get_register_of_actions as nc_court_roa,
    classify_foreclosure_stage,
    is_tax_foreclosure,
)
from scout.writer import write as scout_write
from conclude.handlers import (
    conclude_data as conc_data,
    conclude_write as conc_write,
)
from verify.handlers import (
    verify_data as ver_data,
    verify_write as ver_write,
)
from investigate.handlers import (
    property_state as inv_property_state,
    save_capture as inv_save_capture,
    read_document_handler as inv_read_document,
    update_appraiser_verification as inv_update_verification,
    log_trace as inv_log_trace,
    log_incidental as inv_log_incidental,
    open_question as inv_open_question,
    resolve_question as inv_resolve_question,
    settle_chain as inv_settle_chain,
    flag_review as inv_flag_review,
    court_pull as inv_court_pull,
    pull_deed as inv_pull_deed,
)

_lock = threading.Lock()
PORT = int(os.getenv("PORT", 8000))


# ---------------------------------------------------------------------------
# Route handlers — each returns (status_code, response_dict)
# ---------------------------------------------------------------------------

def _wakecounty_assessor(data: dict) -> tuple[int, dict]:
    search_type = (data.get("search_type") or "").strip().lower()
    fetch_details = bool(data.get("fetch_details", False))

    if search_type == "owner":
        last_name = (data.get("last_name") or "").strip()
        if not last_name:
            return 400, {"error": "last_name is required"}
        result = wc_assessor_owner(
            last_name=last_name,
            first_name=(data.get("first_name") or "").strip(),
            fetch_details=fetch_details,
        )
        return 200, {"count": len(result), "results": result}

    if search_type == "address":
        street_name = (data.get("street_name") or "").strip()
        if not street_name:
            return 400, {"error": "street_name is required"}
        result = wc_assessor_address(
            street_name=street_name,
            street_number=(data.get("street_number") or "").strip(),
            fetch_details=fetch_details,
        )
        return 200, {"count": len(result), "results": result}

    if search_type == "id":
        real_estate_id = (data.get("real_estate_id") or "").strip()
        if not real_estate_id:
            return 400, {"error": "real_estate_id is required"}
        result = search_by_id(real_estate_id, fetch_details=fetch_details)
        return 200, {"count": len(result), "results": result}

    if search_type == "pin":
        map_num = (data.get("map") or "").strip()
        if not map_num:
            return 400, {"error": "map is required for PIN search"}
        result = search_by_pin(
            map_num=map_num,
            sheet=(data.get("sheet") or "").strip(),
            block=(data.get("block") or "").strip(),
            lot=(data.get("lot") or "").strip(),
            fetch_details=fetch_details,
        )
        return 200, {"count": len(result), "results": result}

    if search_type == "account":
        account_id = (data.get("account_id") or "").strip()
        if not account_id:
            return 400, {"error": "account_id is required"}
        return 200, get_account(account_id)

    return 400, {"error": "search_type must be one of: owner, address, id, pin, account"}


def _wakecounty_deeds(data: dict) -> tuple[int, dict]:
    search_type = (data.get("search_type") or "").strip().lower()
    fetch_details = bool(data.get("fetch_details", False))
    page = int(data.get("page") or 1)

    if search_type == "name":
        surname = (data.get("surname") or "").strip()
        if not surname:
            return 400, {"error": "surname is required for name search"}
        result = wc_deeds_name(
            surname=surname,
            first_name=(data.get("first_name") or "").strip(),
            role=(data.get("role") or "both").strip().lower(),
            start_date=(data.get("start_date") or "").strip(),
            end_date=(data.get("end_date") or "").strip(),
            doc_types=data.get("doc_types") or None,
            page=page,
            fetch_details=fetch_details,
        )
        return 200, {"count": len(result), "results": result}

    if search_type == "document":
        doc_number = (data.get("document_number") or "").strip()
        if not doc_number:
            return 400, {"error": "document_number is required"}
        result = search_by_document(doc_number, fetch_details=fetch_details)
        return 200, {"count": len(result), "results": result}

    if search_type == "detail":
        doc_id = (data.get("doc_id") or "").strip()
        if not doc_id:
            return 400, {"error": "doc_id is required"}
        detail = get_document(None, doc_id)
        return 200, {"count": 1, "results": [detail]}

    if search_type == "book_page":
        book = (data.get("book") or "").strip()
        page = (data.get("page") or "").strip()
        if not book or not page:
            return 400, {"error": "book and page are required"}
        result = wc_deeds_book_page(book, page, fetch_details=fetch_details)
        return 200, {"count": len(result), "results": result}

    if search_type == "download_pdf":
        doc_id = (data.get("doc_id") or "").strip()
        if not doc_id:
            return 400, {"error": "doc_id is required"}
        pdf_bytes, pdf_url = wc_deeds_download_pdf(doc_id)
        import base64
        return 200, {
            "doc_id": doc_id,
            "pdf_url": pdf_url,
            "size_bytes": len(pdf_bytes),
            "pdf_base64": base64.b64encode(pdf_bytes).decode(),
        }

    return 400, {"error": "search_type must be: name, document, detail, book_page, or download_pdf"}


def _mecklenburg_assessor(data: dict) -> tuple[int, dict]:
    search_type = (data.get("search_type") or "search").strip().lower()
    term = (data.get("term") or "").strip()
    if not term:
        return 400, {"error": "term is required"}

    if search_type == "suggestions":
        result = meck_suggestions(term)
    elif search_type == "search":
        result = meck_search(term)
    else:
        return 400, {"error": "search_type must be: search or suggestions"}

    return 200, {"count": len(result), "results": result}


def _newhanover_assessor(data: dict) -> tuple[int, dict]:
    search_type = (data.get("search_type") or "").strip().lower()
    page = int(data.get("page") or 1)
    page_size = int(data.get("page_size") or 25)

    if search_type == "address":
        street_name = (data.get("street_name") or "").strip()
        if not street_name:
            return 400, {"error": "street_name is required for address search"}
        result = nh_address(
            street_name=street_name,
            street_number=(data.get("street_number") or "").strip(),
            suffix=(data.get("suffix") or "***").strip(),
            direction=(data.get("direction") or "").strip(),
            page=page,
            page_size=page_size,
        )
        return 200, {"count": len(result), "results": result}

    if search_type == "owner":
        owner_name = (data.get("owner_name") or "").strip()
        if not owner_name:
            return 400, {"error": "owner_name is required for owner search"}
        result = nh_owner(owner_name, page=page, page_size=page_size)
        return 200, {"count": len(result), "results": result}

    if search_type == "parcel":
        parcel_id = (data.get("parcel_id") or "").strip()
        if not parcel_id:
            return 400, {"error": "parcel_id is required for parcel search"}
        result = nh_parcel(parcel_id, page=page, page_size=page_size)
        return 200, {"count": len(result), "results": result}

    return 400, {"error": "search_type must be: address, owner, or parcel"}


def _buncombe_assessor(data: dict) -> tuple[int, dict]:
    search_type = (data.get("search_type") or "search").strip().lower()
    term = (data.get("term") or "").strip()
    page = int(data.get("page") or 1)
    limit = int(data.get("limit") or 21)

    if not term:
        return 400, {"error": "term is required"}

    if search_type == "suggestions":
        result = bunc_suggestions(term)
    elif search_type == "search":
        result = bunc_search(term, page=page, limit=limit)
    else:
        return 400, {"error": "search_type must be: search or suggestions"}

    return 200, {"count": len(result), "results": result}


def _skipgenie(data: dict) -> tuple[int, dict]:
    state = (data.get("state") or "").strip()
    zip_code = (data.get("zip_code") or "").strip()
    if not state and not zip_code:
        return 400, {"error": "at least state or zip_code is required"}

    result = skipgenie_lookup(
        first_name=(data.get("first_name") or "").strip(),
        last_name=(data.get("last_name") or "").strip(),
        middle_name=(data.get("middle_name") or "").strip(),
        street_address=(data.get("street_address") or "").strip(),
        city=(data.get("city") or "").strip(),
        state=state,
        zip_code=zip_code,
    )
    return 200, result


def _nc_court_search(data: dict) -> tuple[int, dict]:
    name = (data.get("name") or "").strip()
    if not name:
        return 400, {"error": "name is required (e.g. 'HAYES' or 'HAYES, LYDIA')"}
    county = (data.get("county") or "").strip()
    parties = nc_court_search(name, county=county)
    return 200, {"count": len(parties), "results": parties}


def _nc_court_roa(data: dict) -> tuple[int, dict]:
    case_url = (data.get("case_url") or "").strip()
    if not case_url:
        return 400, {"error": "case_url is required (from register_of_actions_url in search results)"}
    events = nc_court_roa(case_url)
    stage = classify_foreclosure_stage(events)
    return 200, {"stage": stage, "event_count": len(events), "events": events}


def _scout_write(data: dict) -> tuple[int, dict]:
    """
    Receives Prompt 1 output from n8n and writes to scraper DB.
    Required fields: parcel_id, county.
    Returns: {property_id, created, transfer_count}
    """
    parcel_id = (data.get("parcel_id") or "").strip()
    county    = (data.get("county") or "").strip()
    if not parcel_id:
        return 400, {"error": "parcel_id is required"}
    if not county:
        return 400, {"error": "county is required"}
    result = scout_write(data)
    return 200, result


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

_ROUTES: dict[str, callable] = {
    "/county/wake/assessor": _wakecounty_assessor,
    "/county/wake/deeds": _wakecounty_deeds,
    "/county/mecklenburg/assessor": _mecklenburg_assessor,
    "/county/newhanover/assessor": _newhanover_assessor,
    "/county/buncombe/assessor": _buncombe_assessor,
    "/skipgenie": _skipgenie,
    "/court/nc/search": _nc_court_search,
    "/court/nc/register_of_actions": _nc_court_roa,
    "/scout/write": _scout_write,
    # Investigate layer
    "/investigate/property-state":               lambda d: inv_property_state(d),
    "/investigate/save-capture":                 lambda d: inv_save_capture(d),
    "/investigate/read-document":                lambda d: inv_read_document(d),
    "/investigate/update-appraiser-verification": lambda d: inv_update_verification(d),
    "/investigate/log-trace":                    lambda d: inv_log_trace(d),
    "/investigate/log-incidental":               lambda d: inv_log_incidental(d),
    "/investigate/open-question":                lambda d: inv_open_question(d),
    "/investigate/resolve-question":             lambda d: inv_resolve_question(d),
    "/investigate/settle-chain":                 lambda d: inv_settle_chain(d),
    "/investigate/flag-review":                  lambda d: inv_flag_review(d),
    "/investigate/court-pull":                   lambda d: inv_court_pull(d),
    "/investigate/pull-deed":                    lambda d: inv_pull_deed(d),
    # Conclude layer
    "/conclude/data":                            lambda d: conc_data(d),
    "/conclude/write":                           lambda d: conc_write(d),
    # Verify layer
    "/verify/data":                              lambda d: ver_data(d),
    "/verify/write":                             lambda d: ver_write(d),
}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        handler_fn = _ROUTES.get(path)

        if not handler_fn:
            self._respond(404, {"error": f"unknown route: {path}", "available": list(_ROUTES.keys())})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._respond(400, {"error": "invalid JSON"})
            return

        try:
            with _lock:
                status, result = handler_fn(data)
            self._respond(status, result)
        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def do_GET(self):
        self._respond(200, {"status": "ok", "routes": list(_ROUTES.keys())})

    def _respond(self, status: int, data: dict):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def run():
    server = HTTPServer(("0.0.0.0", PORT), _Handler)
    print(f"[Scraper Server] Listening on port {PORT}")
    for route in _ROUTES:
        print(f"  POST {route}")
    server.serve_forever()


if __name__ == "__main__":
    run()
