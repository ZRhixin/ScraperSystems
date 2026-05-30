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
import threading
import time

from curl_cffi import requests as cffi_requests

from court.nc.session import build_session, _TOKEN_FILE, refresh_waf_token, _TOKEN_FILE, refresh_waf_token

BASE = "https://portal-nc.tylertech.cloud"
_HOME = f"{BASE}/Portal/Home/Dashboard/29"
_SEARCH_URL = f"{BASE}/Portal/SmartSearch/SmartSearch/SmartSearch"
_RESULTS_URL = f"{BASE}/Portal/SmartSearch/SmartSearchResults"
_ROA_API = f"{BASE}/app/api/cases"
_SVC     = f"{BASE}/app/RegisterOfActionsService"

_roa_lock = threading.Lock()

_TAX_PLAINTIFFS = (
    "county of ", "city of ", "town of ", "municipality",
    "tax collector", "treasurer", "board of county",
)


_WAF_SIGNALS = ("awsWafCoo", "Human Verification", "aws-waf-token")


def _is_waf_blocked(resp) -> bool:
    return resp.status_code == 202 or any(sig in resp.text[:600] for sig in _WAF_SIGNALS)


def _invalidate_and_refresh() -> None:
    if _TOKEN_FILE.exists():
        _TOKEN_FILE.unlink()
    refresh_waf_token(headless=False)


def _new_session() -> cffi_requests.Session:
    return build_session()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def _name_variants(name: str) -> list[str]:
    """
    Generate name variants for retrying court searches.

    The portal's behavior is finicky: "HAYES, ALYCE F" returns 0 hits but
    "HAYES, ALYCE" returns 8 (incl. the estate case). To survive name drift
    between SkipGenie/Ancestry sources and the court index, try several forms.
    """
    raw = (name or "").strip()
    if not raw:
        return []

    variants: list[str] = [raw]
    seen = {raw.upper()}

    def _add(v: str) -> None:
        v = " ".join(v.split())
        if v and v.upper() not in seen:
            variants.append(v)
            seen.add(v.upper())

    if "," in raw:
        # "LAST, FIRST MIDDLE" → also try without middle, last-only, FIRST LAST
        last, _, rest = raw.partition(",")
        rest_parts = rest.strip().split()
        if rest_parts:
            first = rest_parts[0]
            _add(f"{last.strip()}, {first}")          # drop middle
            _add(f"{first} {last.strip()}")           # FIRST LAST
        _add(last.strip())                            # LAST only
    else:
        parts = raw.split()
        if len(parts) >= 2:
            last = parts[-1]
            first = parts[0]
            _add(f"{last}, {' '.join(parts[:-1])}")   # LAST, FIRST [MIDDLE]
            _add(f"{last}, {first}")                  # LAST, FIRST (drop middle)
            _add(last)                                # LAST only

    return variants[:4]  # cap at 4 attempts


def _do_search(name: str, court_location: str) -> list[dict]:
    """Issue a single SmartSearch POST/GET cycle. WAF-aware."""
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

    for attempt in range(2):
        s = _new_session()

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

        if _is_waf_blocked(resp):
            if attempt == 0:
                _invalidate_and_refresh()
                continue
            raise RuntimeError("SmartSearch blocked by WAF after token refresh — run: python -m court.nc.session")

        if resp.status_code not in (200, 302):
            raise RuntimeError(f"SmartSearch POST returned {resp.status_code}: {resp.text[:300]}")

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

    return []


_ESTATE_CASE_TYPES = ("estate", "special proceeding")


def _has_estate_hit(parties: list[dict]) -> bool:
    for p in parties:
        for c in (p.get("cases") or []):
            ct = (c.get("case_type") or "").lower()
            code = (c.get("case_type_code") or "").upper()
            if code in ("E", "SP") or any(t in ct for t in _ESTATE_CASE_TYPES):
                return True
    return False


def search_by_name(name: str, county: str = "") -> list[dict]:
    """
    Search NC Courts Portal by party name with multi-variant retry.

    name: last name only ("HAYES") or "LAST, FIRST MIDDLE" format.
    county: optional county filter, e.g. "Wake County". Empty = all locations.

    If the first variant returns 0 parties or 0 estate-type cases, retries
    with stripped middle initial / FIRST LAST / LAST-only formats and merges
    results (dedup by case_number). Stops at the first variant that yields
    any estate hit, or returns the union of all variants tried.
    """
    county = county.strip().title() if county else ""
    court_location = f"{county} County" if county and not county.lower().endswith("county") else (county or "All Locations")

    variants = _name_variants(name)
    if not variants:
        return []

    merged: list[dict] = []
    seen_cases: set[str] = set()

    for v in variants:
        parties = _do_search(v, court_location)

        if parties:
            for p in parties:
                kept_cases = []
                for c in (p.get("cases") or []):
                    cn = c.get("case_number")
                    if cn and cn in seen_cases:
                        continue
                    if cn:
                        seen_cases.add(cn)
                    kept_cases.append(c)
                if kept_cases:
                    merged.append({**p, "cases": kept_cases})

        # Stop early once we've found an estate case under any variant.
        if _has_estate_hit(merged):
            break

    return merged


def _normalize_case_event(evt: dict) -> dict:
    """Normalize a CaseEvents API event (nested structure) to flat {date, event, party, comments}."""
    inner   = evt.get("Event") or {}
    type_id = inner.get("TypeId") or {}
    return {
        "date":     inner.get("FiledDate") or inner.get("EventDate") or inner.get("Date"),
        "event":    type_id.get("Description") or inner.get("EventDescription"),
        "party":    inner.get("PartyDescription"),
        "comments": inner.get("Comments"),
    }


def _get_roa_via_playwright(case_url: str) -> list[dict]:
    """
    WAF fallback for get_register_of_actions.

    The direct /app/api/cases/{id}/registerofactions endpoint sits behind a
    separate ALB target group whose AWSALB sticky-session cookie is not
    established by the /Portal/ SmartSearch warmup.

    Instead: open a headless browser with saved WAF cookies, navigate to the
    ROA React page, and call RegisterOfActionsService/CaseEvents from inside
    the page's JS context (same technique used in pull_document.py).  The
    browser's own session cookies are used for the fetch — WAF never fires.
    """
    from playwright.sync_api import sync_playwright

    if not case_url.startswith("http"):
        case_url = BASE + case_url

    with _roa_lock:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})

            # Seed saved WAF + AWSALB cookies — avoid re-solving CAPTCHA
            if _TOKEN_FILE.exists():
                try:
                    saved = json.loads(_TOKEN_FILE.read_text())
                    for c in saved.get("cookies", []):
                        try:
                            ctx.add_cookies([{
                                "name":   c["name"],
                                "value":  c["value"],
                                "domain": c.get("domain", ".tylertech.cloud"),
                                "path":   c.get("path", "/"),
                            }])
                        except Exception:
                            pass
                except Exception:
                    pass

            page = ctx.new_page()

            # Extract LONG_ID — React router sets window.location.hash after mounting
            long_id = None
            m = re.search(r'#/([A-Fa-f0-9]{80,})', case_url)
            if m:
                long_id = m.group(1)

            page.goto(case_url, wait_until="domcontentloaded", timeout=30000)

            if not long_id:
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                time.sleep(2)
                hash_val = page.evaluate(
                    "() => window.location.hash.replace('#/', '').split('/')[0]"
                )
                if hash_val and len(hash_val) >= 80:
                    long_id = hash_val

            if not long_id:
                print("[ROA] Could not determine LONG_ID from ROA page")
                browser.close()
                return []

            events_url = (
                f"{_SVC}/CaseEvents('{long_id}')"
                f"?mode=portalembed&$top=200&$skip=0"
            )
            data = page.evaluate(
                """async ([url]) => {
                    try {
                        const r = await fetch(url, {
                            credentials: 'include',
                            headers: {
                                'Accept': 'application/json',
                                'X-Requested-With': 'XMLHttpRequest'
                            }
                        });
                        if (!r.ok) return { error: true, status: r.status };
                        return await r.json();
                    } catch (e) {
                        return { error: true, msg: e.toString() };
                    }
                }""",
                [events_url],
            )
            browser.close()

            if isinstance(data, dict) and data.get("error"):
                print(f"[ROA] CaseEvents API error: {data}")
                return []

            events = (data or {}).get("Events", [])
            print(f"[ROA] Playwright fallback returned {len(events)} events")
            return [_normalize_case_event(e) for e in events]


def get_register_of_actions(case_url: str) -> list[dict]:
    """
    Fetch the Register of Actions (event list) for a case.

    case_url: the register_of_actions_url from search results.
              e.g. "/app/RegisterOfActions/?id=ABC123" or full URL.
    Returns a list of case events.

    Falls back to a Playwright-based fetcher if the direct /app/api/ endpoint
    is WAF-blocked (different ALB target group from /Portal/ SmartSearch).
    """
    if not case_url.startswith("http"):
        case_url = BASE + case_url

    match = re.search(r'[?&]id=([^&]+)', case_url)
    if not match:
        # Hash-based or unknown URL format — go straight to Playwright
        return _get_roa_via_playwright(case_url)

    encrypted_id = match.group(1)
    api_url = f"{_ROA_API}/{encrypted_id}/registerofactions"

    for attempt in range(2):
        s = _new_session()
        resp = s.get(
            api_url,
            headers={
                "Accept": "application/json",
                "Referer": case_url,
            },
            timeout=20,
        )

        if _is_waf_blocked(resp):
            if attempt == 0:
                _invalidate_and_refresh()
                continue
            print("[ROA] Direct API WAF-blocked after refresh — trying Playwright fallback")
            return _get_roa_via_playwright(case_url)

        if resp.status_code == 404:
            # /app/api/ sits behind a separate ALB target group — use Playwright fallback
            print("[ROA] Direct API returned 404 — trying Playwright fallback")
            return _get_roa_via_playwright(case_url)

        if resp.status_code != 200:
            raise RuntimeError(f"Register of Actions API returned {resp.status_code}")

        data = resp.json()
        events = data if isinstance(data, list) else (data.get("registerOfActions") or data.get("events") or [])
        return [_normalize_event(e) for e in events]

    # Loop exhausted without returning (both attempts WAF-blocked and refresh failed)
    return _get_roa_via_playwright(case_url)


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
