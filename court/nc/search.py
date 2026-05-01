"""
NC Courts Portal — SmartSearch
https://portal-nc.tylertech.cloud

Statewide search for court cases by party name.
Used for two purposes:
  1. Foreclosure check: find CV cases where plaintiff is a taxing unit
  2. Probate check (Stage 4): find estate/probate cases

Session requirement:
  AWS WAF CAPTCHA protects this site. Run once to establish a session:
      python -m court.nc.session
  Session cookies are saved to court/nc/session_cookies.json and reused
  for ~48 hours before needing a refresh.

Flow:
  POST /Portal/SmartSearch/SmartSearch/SmartSearch  → 302, sets SmartSearchCriteria cookie
  GET  /Portal/SmartSearch/SmartSearchResults?_=ts  → HTML with Kendo Grid JSON

Functions:
  search_by_name(name)              — party name search, returns parties + their cases
  get_register_of_actions(case_url) — case events for a specific case
  classify_foreclosure_stage(events) — map events to foreclosure stage
  is_tax_foreclosure(style)          — check if plaintiff is a taxing unit
"""
import json
import re
import time

from curl_cffi import requests as cffi_requests

from court.nc.session import build_session

BASE = "https://portal-nc.tylertech.cloud"
_HOME = f"{BASE}/Portal/Home/Dashboard/29"
_SEARCH_URL = f"{BASE}/Portal/SmartSearch/SmartSearch/SmartSearch"
_RESULTS_URL = f"{BASE}/Portal/SmartSearch/SmartSearchResults"
_ROA_API = f"{BASE}/app/api/cases"

_TAX_PLAINTIFFS = (
    "county of ", "city of ", "town of ", "municipality",
    "tax collector", "treasurer", "board of county",
)


def _new_session() -> cffi_requests.Session:
    return build_session()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def search_by_name(name: str, county: str = "") -> list[dict]:
    """
    Search NC Courts Portal by party name.

    name: last name only ("HAYES") or "LAST, FIRST MIDDLE" format.
    county: optional county filter, e.g. "Wake County". Empty = all locations.

    Returns a list of matching parties, each with their cases.
    """
    s = _new_session()

    court_location = f"{county} County" if county and not county.lower().endswith("county") else (county or "All Locations")

    payload = {
        "Settings.CaptchaEnabled": "False",
        "Settings.CaptchaDisabledForAuthenticated": "False",
        "caseCriteria.SearchCriteria": name,
        "caseCriteria.JudicialOfficerSearchBy": "",
        "caseCriteria.NameLast": "",
        "caseCriteria.NameFirst": "",
        "caseCriteria.NameMiddle": "",
        "caseCriteria.NameSuffix": "",
        "caseCriteria.AdvancedSearchOptionsOpen": "false",
        "caseCriteria.CourtLocation": court_location,
        "caseCriteria.SearchBy": "SmartSearch",
        "caseCriteria.SearchCases": "true",
        "caseCriteria.SearchByPartyName": "true",
        "caseCriteria.SearchByNickName": "true",
        "caseCriteria.SearchByBusinessName": "true",
        "caseCriteria.UseSoundex": "true",
        "Search": "Submit",
    }

    resp = s.post(
        _SEARCH_URL,
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": _HOME,
            "Origin": BASE,
        },
        allow_redirects=False,
        timeout=30,
    )

    if resp.status_code not in (200, 302):
        raise RuntimeError(f"SmartSearch POST returned {resp.status_code}: {resp.text[:300]}")

    # Brief pause — server needs a moment to prepare results before the GET is ready
    time.sleep(2)

    ts = int(time.time() * 1000)
    results_resp = s.get(
        _RESULTS_URL,
        params={"_": ts},
        headers={
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
            "Referer": f"{BASE}/Portal/SmartSearch/SmartSearch",
        },
        timeout=120,
    )

    return _parse_results(results_resp.text)


def get_register_of_actions(case_url: str) -> list[dict]:
    """
    Fetch the Register of Actions (event list) for a case.

    case_url: the register_of_actions_url from search results.
              e.g. "/app/RegisterOfActions/?id=ABC123" or full URL.
    Returns a list of case events.
    """
    if not case_url.startswith("http"):
        case_url = BASE + case_url

    match = re.search(r'[?&]id=([^&]+)', case_url)
    if not match:
        raise ValueError(f"Cannot extract case id from URL: {case_url}")
    encrypted_id = match.group(1)

    s = _new_session()
    api_url = f"{_ROA_API}/{encrypted_id}/registerofactions"
    resp = s.get(
        api_url,
        headers={
            "Accept": "application/json",
            "Referer": case_url,
        },
        timeout=20,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Register of Actions API returned {resp.status_code}")

    data = resp.json()
    events = data if isinstance(data, list) else (data.get("registerOfActions") or data.get("events") or [])
    return [_normalize_event(e) for e in events]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_results(html: str) -> list[dict]:
    """
    Extract party+case data from the Kendo Grid embedded JSON.
    The data is embedded as: "data":{"Data":[...], "Total": N, ...}
    """
    # Find "data":{"Data":[
    match = re.search(r'"data"\s*:\s*\{\s*"Data"\s*:\s*(\[)', html)
    if not match:
        return []

    raw = _extract_balanced(html, match.start(1), "[", "]")
    if not raw:
        return []

    try:
        parties = json.loads(raw)
    except json.JSONDecodeError:
        return []

    return [_normalize_party(p) for p in parties]


def _extract_balanced(text: str, start: int, open_ch: str, close_ch: str) -> str | None:
    """Extract balanced bracket content starting at position `start`."""
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _normalize_party(p: dict) -> dict:
    return {
        "party_id": p.get("PartyId"),
        "name_last": p.get("NameLast"),
        "name_first": p.get("NameFirst"),
        "case_count": p.get("CaseResultCount", 0),
        "cases": [_normalize_case(c) for c in (p.get("CaseResults") or [])],
    }


def _normalize_case(c: dict) -> dict:
    case_load_url = c.get("CaseLoadUrl") or ""
    full_url = (BASE + case_load_url) if case_load_url and not case_load_url.startswith("http") else case_load_url

    return {
        "node_id": c.get("NodeID"),
        "location": c.get("LocationName"),
        "case_number": c.get("CaseNumber"),
        "style": c.get("Style"),
        "file_date": (c.get("FileDate") or "").replace(" 12:00:00 AM", "").strip(),
        "case_type": (c.get("CaseTypeId") or {}).get("Description"),
        "case_type_code": (c.get("CaseTypeId") or {}).get("Word"),
        "status": (c.get("CaseStatusId") or {}).get("Description"),
        "status_code": (c.get("CaseStatusId") or {}).get("Word"),
        "defendant": c.get("DefendantName"),
        "category": c.get("CaseCategoryKey"),
        "register_of_actions_url": full_url or None,
    }


def _normalize_event(e: dict) -> dict:
    return {
        "date": e.get("FiledDate") or e.get("EventDate") or e.get("date"),
        "event": e.get("EventDescription") or e.get("Description") or e.get("event"),
        "party": e.get("PartyDescription") or e.get("party"),
        "comments": e.get("Comments") or e.get("comments"),
    }


# ---------------------------------------------------------------------------
# Foreclosure helpers
# ---------------------------------------------------------------------------

_FORECLOSURE_EVENTS = {
    "civil judgment":        "POST_JUDGMENT_PRE_SALE",
    "report of sale":        "ACTIVE_UPSET_BIDDING",
    "order of confirmation": "SALE_CONFIRMED",
}

_STAGE_ORDER = ["PRE_JUDGMENT", "POST_JUDGMENT_PRE_SALE", "ACTIVE_UPSET_BIDDING", "SALE_CONFIRMED"]


def classify_foreclosure_stage(events: list[dict]) -> str:
    """
    Given a list of Register of Actions events, return the foreclosure stage.
    Returns one of: NO_CASE, PRE_JUDGMENT, POST_JUDGMENT_PRE_SALE,
                    ACTIVE_UPSET_BIDDING, SALE_CONFIRMED
    """
    if not events:
        return "NO_CASE"

    stage = "PRE_JUDGMENT"
    for ev in events:
        text = (ev.get("event") or "").lower()
        for keyword, mapped_stage in _FORECLOSURE_EVENTS.items():
            if keyword in text:
                if _STAGE_ORDER.index(mapped_stage) > _STAGE_ORDER.index(stage):
                    stage = mapped_stage
    return stage


def is_tax_foreclosure(style: str) -> bool:
    """Returns True if the case style suggests the plaintiff is a taxing unit."""
    low = (style or "").lower()
    return any(kw in low for kw in _TAX_PLAINTIFFS)
