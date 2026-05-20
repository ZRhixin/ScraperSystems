"""
Ancestry.com search — parses the SSR HTML search results page.

Ancestry renders search results server-side into the initial GET response
at https://www.ancestry.com/search/?name=First_Last&count=50&name_x=1_1
The JSON results are embedded in a script block in the HTML.
"""
import json
import re

from curl_cffi import requests as cffi_requests

from . import session as sess

BASE_URL = "https://www.ancestry.com"
SEARCH_URL = f"{BASE_URL}/search/"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)

_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Sec-Ch-Ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": _UA,
}


def _make_session() -> cffi_requests.Session:
    http = cffi_requests.Session(impersonate="chrome124")
    http.cookies.update(sess.load_cookies())
    return http


def _build_name_param(first_name: str, last_name: str) -> str:
    """Ancestry name format: First_Last (underscore-separated)."""
    parts = [p for p in [first_name.strip(), last_name.strip()] if p]
    return "_".join(parts)


def search_person(
    first_name: str = "",
    last_name: str = "",
    birth_year: str = "",
    death_year: str = "",
    birth_year_range: int = 3,
    death_year_range: int = 3,
    state: str = "",
    birth_location: str = "",
    death_location: str = "",
    gender: str = "",
    spouse: str = "",
    father: str = "",
    mother: str = "",
    name_x: str = "1_1",
    count: int = 50,
) -> dict:
    """
    Search Ancestry.com for a person.

    name_x controls name matching:
      "1_1" = exact first + exact last (default)
      "0_1" = any first + exact last  (useful when first name is uncertain)
      "1_0" = exact first + any last

    birth_year_range / death_year_range: ±N years. Default 3 — tight when
      birth_year comes from SkipGenie (a known confident source).

    birth_location / death_location: e.g. "North Carolina" — pins to state,
      much stronger than residence filter. Use when person is known NC resident.

    gender: "m" or "f" — derive from relationship_hint (son/husband=m, daughter/wife=f)
    spouse / father / mother: known relative names for cross-referencing
    """
    if not sess.has_valid_session():
        return {
            "error": "no_session",
            "message": "No Ancestry cookies saved. Log in via Chrome then paste cookies.",
        }

    name_param = _build_name_param(first_name, last_name)
    if not name_param:
        return {"error": "bad_request", "message": "first_name or last_name is required"}

    params: dict = {
        "name": name_param,
        "count": str(count),
        "name_x": name_x,
        "searchMode": "advanced",
    }
    if birth_year:
        params["birth_year"] = str(birth_year)
        params["birth_year_range"] = str(birth_year_range)
    if death_year:
        params["death_year"] = str(death_year)
        params["death_year_range"] = str(death_year_range)
    if state:
        params["residence"] = state
    if birth_location:
        params["birth"] = birth_location
    if death_location:
        params["death"] = death_location
    if gender in ("m", "f"):
        params["gender"] = gender
    if spouse:
        params["spouse"] = spouse.strip()
    if father:
        params["father"] = father.strip()
    if mother:
        params["mother"] = mother.strip()

    http = _make_session()
    try:
        resp = http.get(
            SEARCH_URL,
            params=params,
            headers=_HEADERS,
            timeout=30,
            verify=False,
        )
        if resp.status_code == 401:
            return {"error": "unauthorized", "message": "Session expired — re-export cookies from Chrome"}
        if resp.status_code == 403:
            return {"error": "cloudflare_block", "message": "Cloudflare blocked — cf_clearance cookie may be stale"}
        resp.raise_for_status()
    except Exception as exc:
        return {"error": str(exc)}

    return _parse_html(resp.text, name_param)


_STRIP_HTML = re.compile(r"<[^>]+>")


def _parse_html(html: str, search_name: str) -> dict:
    """
    Extract search results from window.__PRELOADED_STATE__ embedded in the SSR HTML.
    Path: .results.results.items  (each item has a fields[] array)
    """
    m = re.search(r"window\.__PRELOADED_STATE__\s*=\s*(\{.*)", html)
    if not m:
        return {
            "result_count": 0,
            "records": [],
            "error": "parse_failed",
            "message": "window.__PRELOADED_STATE__ not found — page structure may have changed",
        }

    raw = m.group(1)
    end = raw.find("</script>")
    if end != -1:
        raw = raw[:end].rstrip(";")

    try:
        state = json.loads(raw)
    except Exception as exc:
        return {
            "result_count": 0,
            "records": [],
            "error": "json_parse_failed",
            "message": str(exc),
            "raw_snippet": raw[:500],
        }

    results_block = state.get("results", {}).get("results", {})
    hit_count = results_block.get("hitCount", 0)
    items = results_block.get("items", [])

    records = [_parse_item(item) for item in items]
    # Filter out items that are fully veiled (no useful data)
    records = [r for r in records if r.get("person_name")]

    return {
        "result_count": hit_count,
        "returned": len(records),
        "records": records,
    }


def _strip(text: str) -> str:
    return _STRIP_HTML.sub("", text).strip()


def _parse_item(item: dict) -> dict:
    """
    Parse one search result item from Ancestry's __PRELOADED_STATE__.
    Fields array: [{ label, text, veiled, date?, place? }, ...]
    """
    fields_by_label: dict[str, dict] = {}
    for f in item.get("fields", []):
        label = f.get("label", "").strip()
        if label:
            fields_by_label[label] = f

    def _field_text(label: str) -> str:
        f = fields_by_label.get(label, {})
        if f.get("veiled"):
            return ""
        return _strip(f.get("text") or "")

    def _field_date(label: str) -> str:
        f = fields_by_label.get(label, {})
        if f.get("veiled"):
            return ""
        return (f.get("date") or "").strip()

    def _field_place(label: str) -> str:
        f = fields_by_label.get(label, {})
        if f.get("veiled"):
            return ""
        return (f.get("place") or "").strip()

    # Build parents list from Mother/Father fields
    parents = []
    for label in ("Father", "Mother"):
        name = _field_text(label)
        if name:
            parents.append(name)

    # Build children list
    children = [_field_text(f) for f in fields_by_label if "Child" in f]
    children = [c for c in children if c]

    # Spouse: try common labels
    spouse = ""
    for label in ("Spouse", "Husband", "Wife"):
        spouse = _field_text(label)
        if spouse:
            break

    record_url = item.get("recordUrl") or ""
    if record_url and not record_url.startswith("http"):
        record_url = f"{BASE_URL}{record_url}"

    return {
        "record_id":      item.get("recordId") or "",
        "collection_id":  item.get("collectionId") or "",
        "record_type":    item.get("primaryCategory") or item.get("collectionTitle") or "other",
        "collection":     item.get("collectionTitle") or "",
        "person_name":    _field_text("Name") or _strip(item.get("nameField", {}).get("text") or ""),
        "dob":            _field_date("Birth"),
        "dod":            _field_date("Death"),
        "birth_location": _field_place("Birth"),
        "death_location": _field_place("Death"),
        "spouse_name":    spouse,
        "parents":        parents,
        "children":       children,
        "siblings":       [],
        "residence":      _field_text("Residence"),
        "source_url":     record_url,
        "confidence":     "high" if item.get("hasRecordViewRights") else "medium",
        "has_image":      bool(item.get("imageIds")),
        "viewable":       bool(item.get("hasRecordViewRights")),
    }


def get_record(record_id: str) -> dict:
    """Fetch a specific record page by its Ancestry record URL or ID."""
    if not sess.has_valid_session():
        return {"error": "no_session"}

    # record_id may be a full URL or just an ID
    if record_id.startswith("http"):
        url = record_id
    else:
        url = f"{BASE_URL}/discoveryui-content/view/{record_id}"

    http = _make_session()
    try:
        resp = http.get(url, headers=_HEADERS, timeout=30, verify=False)
        if resp.status_code in (401, 403):
            return {"error": "unauthorized"}
        resp.raise_for_status()
    except Exception as exc:
        return {"error": str(exc)}

    return _parse_html(resp.text, record_id)
