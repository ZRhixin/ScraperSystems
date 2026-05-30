"""
NC Courts Portal — Document Downloader

Downloads probate documents from the NC courts portal.

Flow:
  1. Playwright browser session (same session that solved CAPTCHA) navigates to
     the ROA page and calls RegisterOfActionsService/CaseEvents via in-page fetch.
  2. curl_cffi downloads each PDF via /Portal/DocumentViewer/DisplayDoc using
     the portal session cookies saved by session.py.

URL formats accepted:
  - ROA hash URL:  /app/RegisterOfActions/#/LONG_ID/anon/portalembed
  - ROA query URL: /app/RegisterOfActions/?id=SHORT_ID  (triggers browser nav)
  - Direct PDF:    /app/.../.pdf  (downloaded directly)

Usage:
  from court.nc.pull_document import pull_court_document
  result = pull_court_document(roa_url)
"""
import re
import time
import json
import threading
from pathlib import Path
from urllib.parse import quote

from curl_cffi import requests as cffi_requests

from court.nc.session import build_session, _PORTAL_URL, _TOKEN_FILE
from court.nc.probate_extract import extract_probate

BASE    = "https://portal-nc.tylertech.cloud"
SVC     = f"{BASE}/app/RegisterOfActionsService"
DISPLAY = f"{BASE}/Portal/DocumentViewer/DisplayDoc"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_playwright_lock = threading.Lock()


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _extract_roa_hash_id(url: str) -> str | None:
    """Extract LONG_ID from a hash-based ROA URL: #/LONG_ID/anon/..."""
    m = re.search(r'#/([A-Fa-f0-9]{80,})', url)
    return m.group(1) if m else None


def _extract_query_id(url: str) -> str | None:
    """Extract SHORT_ID from a ?id= ROA URL."""
    m = re.search(r'[?&]id=([A-Za-z0-9+/=%_-]{20,})', url)
    return m.group(1) if m else None


def _is_direct_pdf_url(url: str) -> bool:
    return url.lower().endswith(".pdf") or "/documents/" in url.lower()


# ---------------------------------------------------------------------------
# Direct PDF download (path 1)
# ---------------------------------------------------------------------------

def _download_direct_pdf(url: str, session: cffi_requests.Session) -> bytes | None:
    resp = session.get(url, timeout=30, allow_redirects=True)
    if resp.status_code == 200 and b"%PDF" in resp.content[:8]:
        return resp.content
    return None


# ---------------------------------------------------------------------------
# Document download via /Portal/DocumentViewer/DisplayDoc (path 2)
# ---------------------------------------------------------------------------

def _download_via_display_doc(
    fragment_id: str,
    case_num: str,
    location_id: str,
    case_id: str,
    doc_type: str,
    doc_name: str,
    event_name: str,
    session: cffi_requests.Session,
) -> bytes | None:
    """
    Download a PDF by calling /Portal/DocumentViewer/DisplayDoc.
    The endpoint is on /Portal/ and works with the standard WAF session cookies.
    docTypeId=12 is constant and accepted by the portal for all document types.
    """
    url = (
        f"{DISPLAY}"
        f"?documentID={fragment_id}"
        f"&caseNum={quote(case_num)}"
        f"&locationId={location_id}"
        f"&caseId={case_id}"
        f"&docTypeId=12"
        f"&isVersionId=false"
        f"&docType={quote(doc_type)}"
        f"&docName={quote(doc_name)}"
        f"&eventName={quote(event_name)}"
    )
    resp = session.get(
        url,
        headers={"Referer": f"{BASE}/app/RegisterOfActions/"},
        allow_redirects=True,
        timeout=30,
    )
    if resp.status_code == 200 and b"%PDF" in resp.content[:8]:
        return resp.content
    return None


# ---------------------------------------------------------------------------
# CaseEvents via Playwright in-page fetch
# ---------------------------------------------------------------------------

def _normalize_case_event(evt: dict) -> dict:
    inner = evt.get("Event") or {}
    type_id = inner.get("TypeId") or {}
    return {
        "date":     inner.get("FiledDate") or inner.get("EventDate") or inner.get("Date"),
        "event":    type_id.get("Description") or inner.get("EventDescription"),
        "party":    inner.get("PartyDescription"),
        "comments": inner.get("Comments"),
    }


def _get_case_documents_via_playwright(roa_url: str) -> tuple[list[dict], list[dict]]:
    """
    Open a browser, solve CAPTCHA if needed, navigate to the ROA page,
    then use in-page fetch to call CaseEvents API.

    Returns (doc_descriptors, normalized_events):
      doc_descriptors: [{ fragment_id, case_num, location_id, case_id, doc_type, doc_name, event_name }]
      normalized_events: [{ date, event, party, comments }]
    """
    from playwright.sync_api import sync_playwright

    docs = []
    raw_events = []
    with _playwright_lock:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx  = browser.new_context(viewport={"width": 1280, "height": 900}, user_agent=_UA)
            page = ctx.new_page()

            # Step 1: portal home — solve CAPTCHA
            print("[pull_document] Opening portal. Solve CAPTCHA if prompted...")
            page.goto(_PORTAL_URL, timeout=60000)
            deadline = time.time() + 600
            while time.time() < deadline:
                try:
                    title = page.title()
                except Exception:
                    time.sleep(1)
                    continue
                if title and title != "Human Verification":
                    print(f"[pull_document] CAPTCHA passed: {title}")
                    break
                time.sleep(1)
            else:
                browser.close()
                raise TimeoutError("CAPTCHA not solved within 10 minutes")

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            time.sleep(1)

            # Save updated cookies
            raw = ctx.cookies()
            cookies = [{"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/")} for c in raw]
            _TOKEN_FILE.write_text(json.dumps({"saved_at": time.time(), "cookies": cookies}, indent=2))

            # Step 2: navigate to ROA page
            # If we have a LONG_ID hash URL, use it directly.
            # If we have a ?id= URL, navigate to it and capture the final URL.
            long_id = _extract_roa_hash_id(roa_url)
            target_url = roa_url if roa_url.startswith("http") else BASE + roa_url

            if not long_id:
                # Navigate to ?id= URL and check if we get redirected to a hash URL
                print(f"[pull_document] Navigating to ROA URL to discover LONG_ID...")
                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                time.sleep(2)
                final_url = page.evaluate("() => window.location.href")
                long_id = _extract_roa_hash_id(final_url or "")
                if long_id:
                    print(f"[pull_document] LONG_ID discovered from redirect: {long_id[:20]}...")
                else:
                    # Page might still have data — try extracting from JS scope
                    hash_id = page.evaluate("() => window.location.hash.replace('#/', '').split('/')[0]")
                    if hash_id and len(hash_id) >= 80:
                        long_id = hash_id
                        print(f"[pull_document] LONG_ID from hash: {long_id[:20]}...")
            else:
                print(f"[pull_document] Navigating to ROA (LONG_ID={long_id[:20]}...)...")
                page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                time.sleep(3)

            if not long_id:
                browser.close()
                print("[pull_document] Could not determine LONG_ID — cannot fetch CaseEvents")
                return [], []

            print(f"[pull_document] Fetching CaseEvents for LONG_ID={long_id[:20]}...")
            events_url = f"{SVC}/CaseEvents('{long_id}')?mode=portalembed&$top=200&$skip=0"
            events_data = page.evaluate(
                "async ([url]) => { try { const r = await fetch(url, {credentials: 'include', headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}}); if (!r.ok) return {error: true, status: r.status}; return await r.json(); } catch(e) { return {error: true, msg: e.toString()}; } }",
                [events_url]
            )

            if events_data.get("error"):
                browser.close()
                print(f"[pull_document] CaseEvents error: {events_data}")
                return [], []

            case_id  = str(events_data.get("CaseId", ""))
            events   = events_data.get("Events", [])
            raw_events = [_normalize_case_event(e) for e in events]

            # Also get case summary for caseNum and locationId
            summary_url = f"{SVC}/CaseSummariesSlim?key={long_id}&mode=portalembed"
            summary = page.evaluate(
                "async ([url]) => { try { const r = await fetch(url, {credentials: 'include', headers: {'Accept': 'application/json'}}); if (!r.ok) return {}; return await r.json(); } catch(e) { return {}; } }",
                [summary_url]
            )
            header      = summary.get("CaseSummaryHeader") or {}
            case_num    = header.get("CaseNumber") or ""
            location_id = str(header.get("NodeId") or "")

            browser.close()

            for evt in events:
                event_desc = ((evt.get("Event") or {}).get("TypeId") or {}).get("Description") or ""
                for doc in (evt.get("Event") or {}).get("Documents", []):
                    doc_name = doc.get("DocumentName") or event_desc or "Document"
                    doc_type = ((doc.get("DocumentTypeID") or {}).get("Word") or "Other")
                    for ver in doc.get("DocumentVersions", []):
                        for frag in ver.get("DocumentFragments", []):
                            fid = frag.get("DocumentFragmentID")
                            if fid and not frag.get("fArchived") == "1":
                                docs.append({
                                    "fragment_id":  fid,
                                    "case_num":     case_num,
                                    "location_id":  location_id,
                                    "case_id":      case_id,
                                    "doc_type":     doc_type,
                                    "doc_name":     doc_name,
                                    "event_name":   event_desc or doc_name,
                                })

    return docs, raw_events


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def pull_court_document(url: str) -> dict:
    """
    Download and extract court documents from the NC courts portal.

    url: ROA hash URL (#/LONG_ID/...), ROA query URL (?id=...), or direct PDF URL.

    Returns:
      {
        "case_id": str,
        "events":  [{ "date": str, "event": str, "party": str, "comments": str }],
        "documents": [{ "url": str, "doc_name": str, "extraction": {...} }],
        "error": str | null
      }
    """
    session  = build_session()
    case_id  = None
    docs_out = []

    # Path 1: direct PDF URL
    if _is_direct_pdf_url(url):
        pdf = _download_direct_pdf(url, session)
        if pdf:
            docs_out.append({"url": url, "doc_name": "Document", "extraction": extract_probate(pdf)})
        return {
            "case_id":   case_id,
            "events":    [],
            "documents": docs_out,
            "error":     None if docs_out else "Could not download PDF",
        }

    # Path 2: ROA URL — discover documents via Playwright, then download via DisplayDoc
    try:
        doc_descriptors, events_out = _get_case_documents_via_playwright(url)
    except Exception as exc:
        return {
            "case_id":   None,
            "events":    [],
            "documents": [],
            "error":     f"Playwright document discovery failed: {exc}",
        }

    if not doc_descriptors and not events_out:
        return {
            "case_id":   None,
            "events":    [],
            "documents": [],
            "error":     "No documents found in CaseEvents (case may have no public filings)",
        }

    case_id = (doc_descriptors[0].get("case_id") if doc_descriptors else None)

    for desc in doc_descriptors:
        pdf = _download_via_display_doc(
            fragment_id=desc["fragment_id"],
            case_num=desc["case_num"],
            location_id=desc["location_id"],
            case_id=desc["case_id"],
            doc_type=desc["doc_type"],
            doc_name=desc["doc_name"],
            event_name=desc["event_name"],
            session=session,
        )
        if pdf:
            extraction = extract_probate(pdf)
            docs_out.append({
                "url":      f"{DISPLAY}?documentID={desc['fragment_id']}&caseNum={desc['case_num']}",
                "doc_name": desc["doc_name"],
                "extraction": extraction,
            })

    return {
        "case_id":   case_id,
        "events":    events_out,
        "documents": docs_out,
        "error":     None if (docs_out or events_out) else "Documents found but all downloads failed",
    }
