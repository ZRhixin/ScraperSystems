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
    POST /court/nc/pull-document        — url (ROA or doc URL → probate extraction)
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
from court.nc.session import load_waf_token, refresh_waf_token, _TOKEN_FILE
from court.nc.pull_document import pull_court_document
from scout.writer import write as scout_write
from conclude.handlers import (
    conclude_data as conc_data,
    conclude_write as conc_write,
)
from property.handlers import property_full_research
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
from ancestryapi.client import search as ancestry_search, search_paged as ancestry_search_paged, record_detail as ancestry_record, household_members as ancestry_household
from ncvoter.search import lookup as ncvoter_lookup
from heir.handlers import (
    create_session as heir_create_session,
    write_person as heir_write_person,
    load_persons as heir_load_persons,
    load_obituary_texts as heir_load_obituary_texts,
    write_heir_tree as heir_write_heir_tree,
    filter_cascade as heir_filter_cascade,
    queue_persons as heir_queue_persons,
    next_person as heir_next_person,
    complete_person as heir_complete_person,
    queue_status as heir_queue_status,
    claim_fa_trigger as heir_claim_fa_trigger,
    write_ancestry as heir_write_ancestry,
    load_ancestry_records as heir_load_ancestry_records,
    recover_stuck_sessions as heir_recover_stuck,
    queue_recover as heir_queue_recover,
    write_voter_record as heir_write_voter,
    load_voter_records as heir_load_voter,
    write_deed_finding as heir_write_deed_finding,
    write_court_findings as heir_write_court_findings,
    load_court_findings as heir_load_court_findings,
    upsert_person as heir_upsert_person,
    load_person as heir_load_person,
    apply_probate_finding as heir_apply_probate_finding,
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
        state = "NC"  # all properties are in NC; broaden to statewide rather than reject

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


def _nc_court_session_status(_data: dict) -> tuple[int, dict]:
    """Returns whether the AWS WAF token is valid and when it was saved."""
    import time
    token = load_waf_token()
    if not token:
        return 200, {
            "valid": False,
            "message": "No valid session. Open the noVNC browser and solve the captcha.",
            "vnc_url": "http://170.187.145.60:6080/vnc.html",
        }
    data = {}
    try:
        data = json.loads(_TOKEN_FILE.read_text())
    except Exception:
        pass
    saved_at = data.get("saved_at", 0)
    age_hours = (time.time() - saved_at) / 3600
    return 200, {
        "valid": True,
        "saved_at": saved_at,
        "age_hours": round(age_hours, 1),
        "message": f"Session valid. Saved {age_hours:.1f}h ago.",
    }


_captcha_thread: threading.Thread | None = None
_captcha_status = {"running": False, "result": None}


def _nc_court_refresh_session(_data: dict) -> tuple[int, dict]:
    """
    Launches Chromium on the virtual display (:99).
    User opens noVNC at port 6080 and solves the captcha.
    The browser closes automatically once the portal loads.
    """
    global _captcha_thread, _captcha_status

    if _captcha_status["running"]:
        return 200, {
            "status": "already_running",
            "message": "Browser already open. Connect to noVNC and solve the captcha.",
            "vnc_url": "http://170.187.145.60:6080/vnc.html",
        }

    def _run():
        global _captcha_status
        _captcha_status = {"running": True, "result": None}
        try:
            token = refresh_waf_token(headless=False)
            _captcha_status = {"running": False, "result": "success", "token_prefix": token[:12] + "..."}
        except Exception as exc:
            _captcha_status = {"running": False, "result": "error", "error": str(exc)}

    _captcha_thread = threading.Thread(target=_run, daemon=True)
    _captcha_thread.start()

    return 200, {
        "status": "browser_launched",
        "message": "Chromium is open on the virtual display. Connect to noVNC and solve the captcha.",
        "vnc_url": "http://170.187.145.60:6080/vnc.html",
    }


def _nc_captcha_status(_data: dict) -> tuple[int, dict]:
    return 200, _captcha_status


def _nc_pull_document(data: dict) -> tuple[int, dict]:
    """
    Download and extract a probate/court document from the NC courts portal.

    Required: url  (ROA URL, case URL, or direct document URL)
    Optional: property_id, session_id (heir session — for context only, not used in download)

    Returns: { case_id, documents: [{ url, extraction }], error }
    The extraction contains: document_type, decedent_name, named_persons, family_tree, summary.
    """
    url = (data.get("url") or "").strip()
    if not url:
        return 400, {"error": "url is required"}
    if not url.startswith(("http://", "https://")):
        return 400, {"error": "url must start with http:// or https://"}

    result = pull_court_document(url)
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
    return 200, {
        "stage":        stage,
        "event_count":  len(events),
        "events":       events,
        "roa_unavailable": len(events) == 0,
        "note": None if events else "Register of Actions unavailable — WAF blocked. Run: python -m court.nc.session to refresh token.",
    }


_JS_WALL_SIGNALS = [
    "enable javascript",
    "please enable javascript",
    "just a moment",
    "checking your browser",
    "enable cookies",
    "please turn javascript on",
]

_playwright_lock = threading.Lock()


def _html_to_text(raw_html: str) -> str:
    import html as html_mod
    import re
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def _is_js_wall(text: str) -> bool:
    if len(text) > 800:
        return False
    lower = text.lower()
    return any(signal in lower for signal in _JS_WALL_SIGNALS)


def _fetch_with_playwright(url: str, max_chars: int) -> str:
    try:
        from playwright.sync_api import sync_playwright
        with _playwright_lock:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass  # networkidle timeout is ok — grab what we have
                content = page.content()
                browser.close()
        return _html_to_text(content)[:max_chars]
    except Exception as exc:
        print(f"[Playwright] {url} -> {exc}")
        return ""


def _fetch_page(data: dict) -> tuple[int, dict]:
    """
    Fetch the text content of a URL for obituary extraction.
    Uses curl_cffi first; falls back to Playwright for JS-rendered pages
    (legacy.com, tributearchive.com, etc.).
    Required: url
    Returns:  { url, text, char_count, truncated, js_rendered }
    """
    import re
    from curl_cffi import requests as cffi_requests

    url = (data.get("url") or "").strip()
    if not url:
        return 400, {"error": "url is required"}
    if not url.startswith(("http://", "https://")):
        return 400, {"error": "url must start with http:// or https://"}

    max_chars = int(data.get("max_chars") or 8000)
    js_rendered = False

    try:
        resp = cffi_requests.get(
            url,
            impersonate="chrome120",
            timeout=20,
            verify=False,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
            },
        )
        text = _html_to_text(resp.text)
    except Exception as exc:
        text = ""

    if _is_js_wall(text) or not text:
        print(f"[fetch-page] JS wall detected for {url} — falling back to Playwright")
        text = _fetch_with_playwright(url, max_chars)
        js_rendered = True

    truncated = len(text) > max_chars
    return 200, {
        "url": url,
        "text": text[:max_chars],
        "char_count": min(len(text), max_chars),
        "truncated": truncated,
        "js_rendered": js_rendered,
    }


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
# Ancestry.com
# ---------------------------------------------------------------------------

def _ancestry_search(data: dict) -> tuple[int, dict]:
    collection_id = (data.get("collection_id") or "").strip()
    kwargs = dict(
        first_name=(data.get("first_name") or "").strip(),
        last_name=(data.get("last_name") or "").strip(),
        birth_year=str(data.get("birth_year") or "").strip(),
        death_year=str(data.get("death_year") or "").strip(),
        birth_year_range=int(data.get("birth_year_range") or 3),
        death_year_range=int(data.get("death_year_range") or 3),
        state=(data.get("state") or "NC").strip(),
        birth_location=(data.get("birth_location") or "").strip(),
        death_location=(data.get("death_location") or "").strip(),
        gender=(data.get("gender") or "").strip(),
        spouse=(data.get("spouse") or "").strip(),
        father=(data.get("father") or "").strip(),
        mother=(data.get("mother") or "").strip(),
        name_x=(data.get("name_x") or "1_1").strip(),
        collection_id=collection_id,
    )
    # Ancestry serves up to 50 results per SSR page (count=50 is the max effective value).
    # Paginate via pg= parameter, up to 3 pages = 150 records total.
    if collection_id:
        result = ancestry_search_paged(max_pages=3, page_size=50, **kwargs)
    else:
        result = ancestry_search(count=int(data.get("count") or 50), **kwargs)
    return 200, result


def _ancestry_record(data: dict) -> tuple[int, dict]:
    record_id = (data.get("record_id") or "").strip()
    if not record_id:
        return 400, {"error": "record_id is required"}
    return 200, ancestry_record(record_id)


def _ancestry_search_and_save(data: dict) -> tuple[int, dict]:
    """
    Atomic search + DB write. Saves the full raw API result to heir_ancestry_records
    (with children/parents/spouse intact) and returns a compact summary to the LLM.

    LLMs called the previous /ancestry/search + /heir/write-ancestry pair as two
    separate tools and would re-summarize the records[] payload in between,
    dropping structured fields. This endpoint removes that opportunity for loss.

    Required: session_id, property_id, plus all /ancestry/search params.
    Optional: person_id, search_context (passed through as search_name fallback).
    Returns:  { result_count, returned, records_summary: [...], saved: N }
    """
    session_id  = data.get("session_id")
    property_id = data.get("property_id")
    if not session_id or not property_id:
        return 400, {"error": "session_id and property_id are required"}

    status, result = _ancestry_search(data)
    if status != 200 or "error" in result:
        return status, result

    records = result.get("records") or []

    search_name = (
        data.get("search_name")
        or " ".join(filter(None, [(data.get("first_name") or "").strip(),
                                   (data.get("last_name") or "").strip()]))
        or (data.get("mother") or data.get("father") or "").strip()
        or "unknown"
    ).strip()

    write_payload = {
        "session_id":        session_id,
        "property_id":       property_id,
        "person_id":         data.get("person_id"),
        "search_name":       search_name,
        "search_first":      data.get("first_name") or "",
        "search_last":       data.get("last_name") or "",
        "search_birth_year": str(data.get("birth_year") or ""),
        "search_death_year": str(data.get("death_year") or ""),
        "search_state":      data.get("state") or "NC",
        "records":           records,
    }
    _w_status, w_result = heir_write_ancestry(write_payload)

    # Rank records by relevance before capping — prevents correct records buried
    # deep in Ancestry's natural sort order from being invisible to the LLM.
    # Scoring: +3 state/location match, +2 death year ±2, +1 birth year ±5.
    target_death_year = int(data.get("death_year") or 0)
    target_birth_year = int(data.get("birth_year") or 0)
    target_state      = (data.get("state") or "").strip().lower()

    _STATE_ALIASES = {"nc": ["nc", "north carolina"], "sc": ["sc", "south carolina"]}
    state_terms = _STATE_ALIASES.get(target_state, [target_state]) if target_state else []

    def _relevance(r: dict) -> int:
        score = 0
        loc = (r.get("death_location") or "").lower()
        if state_terms and any(t in loc for t in state_terms):
            score += 3
        if target_death_year:
            try:
                ry = int(str(r.get("dod") or "")[:4])
                if abs(ry - target_death_year) <= 2:
                    score += 2
            except (ValueError, TypeError):
                pass
        if target_birth_year:
            try:
                ry = int(str(r.get("dob") or "")[:4])
                if abs(ry - target_birth_year) <= 5:
                    score += 1
            except (ValueError, TypeError):
                pass
        return score

    ranked = sorted(records, key=_relevance, reverse=True)

    summary = []
    for r in ranked[:50]:
        summary.append({
            "record_id":     r.get("record_id"),
            "collection_id": r.get("collection_id"),
            "collection":    r.get("collection"),
            "person_name":   r.get("person_name"),
            "dob":           r.get("dob"),
            "dod":           r.get("dod"),
            "death_location": r.get("death_location"),
            "spouse_name":   r.get("spouse_name"),
            "children":      r.get("children") or [],
            "parents":       r.get("parents") or [],
            "source_url":    r.get("source_url") or (
                f"https://www.ancestry.com/search/collections/{r['collection_id']}/records/{r['record_id']}"
                if r.get("collection_id") and r.get("record_id") else ""
            ),
        })

    return 200, {
        "result_count":    result.get("result_count"),
        "returned":        result.get("returned"),
        "saved":           w_result.get("saved", 0) if isinstance(w_result, dict) else 0,
        "records_summary": summary,
        "search_name":     search_name,
    }


def _ancestry_record_and_save(data: dict) -> tuple[int, dict]:
    """
    Fetch a single Ancestry record's detail page and persist it.

    Required: session_id, property_id, record_id (or full URL)
    Returns:  { record: {...}, saved: 1 }
    """
    session_id  = data.get("session_id")
    property_id = data.get("property_id")
    record_id   = (data.get("record_id") or "").strip()
    if not session_id or not property_id:
        return 400, {"error": "session_id and property_id are required"}
    if not record_id:
        return 400, {"error": "record_id is required"}

    result = ancestry_record(record_id)
    if "error" in result:
        return 200, result

    records = result.get("records") or []
    if records:
        heir_write_ancestry({
            "session_id":   session_id,
            "property_id":  property_id,
            "person_id":    data.get("person_id"),
            "search_name":  records[0].get("person_name") or record_id,
            "search_state": data.get("state") or "NC",
            "records":      records,
        })

    return 200, {
        "record": records[0] if records else None,
        "saved":  len(records),
    }


def _ancestry_household(data: dict) -> tuple[int, dict]:
    """
    Return all members of a census household given any record URL from that household.

    Required: record_url (Ancestry census record URL, e.g. /search/collections/2442/records/...)
    Returns:  { result_count, records: [{person_name, relationship_to_head, dob, ...}] }

    Use when a person's children cannot be found via obituary — census household
    members include all children living at home at the time of the census.
    """
    record_url = (data.get("record_url") or "").strip()
    if not record_url:
        return 400, {"error": "record_url is required"}
    return 200, ancestry_household(record_url)


# ---------------------------------------------------------------------------
# Perplexity web search
# ---------------------------------------------------------------------------

def _perplexity_search(d: dict):
    import urllib.request
    query = d.get("query", "").strip()
    if not query:
        return 400, {"error": "query is required"}
    api_key = os.getenv("PERPLEXITY_API_KEY", "")
    if not api_key:
        return 500, {"error": "PERPLEXITY_API_KEY not set"}
    payload = json.dumps({
        "model": "sonar",
        "messages": [{"role": "user", "content": query}],
        "max_tokens": 1024,
    }).encode()
    req = urllib.request.Request(
        "https://api.perplexity.ai/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
        answer = body["choices"][0]["message"]["content"]
        return 200, {"query": query, "answer": answer}
    except Exception as e:
        return 500, {"error": str(e)}


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
    "/court/nc/session-status":       _nc_court_session_status,
    "/court/nc/refresh-session":      _nc_court_refresh_session,
    "/court/nc/captcha-status":       _nc_captcha_status,
    "/court/nc/pull-document":         _nc_pull_document,
    "/court/nc/search": _nc_court_search,
    "/court/nc/register_of_actions": _nc_court_roa,
    "/fetch-page":                               _fetch_page,
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
    # Property full research (Writer Agent context loader)
    "/property/full-research":                   lambda d: property_full_research(d),
    # Conclude layer
    "/conclude/data":                            lambda d: conc_data(d),
    "/conclude/write":                           lambda d: conc_write(d),
    # Verify layer
    "/verify/data":                              lambda d: ver_data(d),
    "/verify/write":                             lambda d: ver_write(d),
    # Heir tracer layer
    "/heir/session":                             lambda d: heir_create_session(d),
    "/heir/write-person":                        lambda d: heir_write_person(d),
    "/heir/persons":                             lambda d: heir_load_persons(d),
    "/heir/obituary-text":                       lambda d: heir_load_obituary_texts(d),
    "/heir/write":                               lambda d: heir_write_heir_tree(d),
    "/heir/filter-cascade":                      lambda d: heir_filter_cascade(d),
    # Queue-based worker pattern (v2 architecture)
    "/heir/queue-persons":                       lambda d: heir_queue_persons(d),
    "/heir/next-person":                         lambda d: heir_next_person(d),
    "/heir/complete-person":                     lambda d: heir_complete_person(d),
    "/heir/queue-status":                        lambda d: heir_queue_status(d),
    "/heir/claim-fa-trigger":                    lambda d: heir_claim_fa_trigger(d),
    "/heir/write-ancestry":                      lambda d: heir_write_ancestry(d),
    "/heir/ancestry-records":                    lambda d: heir_load_ancestry_records(d),
    "/heir/recover-stuck":                       lambda d: heir_recover_stuck(d),
    "/heir/queue-recover":                       lambda d: heir_queue_recover(d),
    # v2 voter + deed finding storage
    "/heir/write-voter":                         lambda d: heir_write_voter(d),
    "/heir/voter-records":                       lambda d: heir_load_voter(d),
    "/heir/write-deed-finding":                  lambda d: heir_write_deed_finding(d),
    "/heir/write-court-findings":                lambda d: heir_write_court_findings(d),
    "/heir/apply-probate-finding":               lambda d: heir_apply_probate_finding(d),
    "/heir/court-findings":                      lambda d: heir_load_court_findings(d),
    # v3 progressive DB writes and person lookup
    "/heir/upsert-person":                       lambda d: heir_upsert_person(d),
    "/heir/load-person":                         lambda d: heir_load_person(d),
    # Ancestry.com genealogy search
    "/ancestry/search":                          lambda d: _ancestry_search(d),
    "/ancestry/record":                          lambda d: _ancestry_record(d),
    "/ancestry/search-and-save":                 lambda d: _ancestry_search_and_save(d),
    "/ancestry/record-and-save":                 lambda d: _ancestry_record_and_save(d),
    "/ancestry/household":                       lambda d: _ancestry_household(d),
    # Perplexity web search
    "/search/perplexity":                        lambda d: _perplexity_search(d),
    # NC Voter Registration — living status + married name discovery
    "/voter/nc/lookup":                          lambda d: (200, ncvoter_lookup(
        last_name=d.get("last_name",""),
        first_name=d.get("first_name",""),
        middle_initial=d.get("middle_initial", d.get("middle_name",""))[:1],
        birth_year=d.get("birth_year",""),
        county=d.get("county",""),
        include_removed=bool(d.get("include_removed", False)),
    )),
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
