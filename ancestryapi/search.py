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
    collection_id: str = "",
    offset: int = 0,
) -> dict:
    """
    Search Ancestry.com for a person.

    name_x: "1_1" exact first+last, "0_1" any first+exact last, "1_0" exact first+any last.

    collection_id: restrict to a specific Ancestry collection, e.g.:
      "61843" = U.S. Obituary Collection (recommended for heir research)
      "2442"  = U.S., SSDI, 1935-2014
      ""      = global search across all collections (noisier)

    birth_location / death_location: plain text e.g. "North Carolina".
      NOTE: Ancestry global search ignores these filters. Use collection_id
      to narrow results instead — collection-specific search is far more precise.

    gender: "m" or "f"
    spouse / father / mother: known relative names for cross-referencing
    """
    if not sess.has_valid_session():
        return {
            "error": "no_session",
            "message": "No Ancestry cookies saved. Log in via Chrome then paste cookies.",
        }

    name_param = _build_name_param(first_name, last_name)
    if not name_param and not mother and not father:
        return {"error": "bad_request", "message": "first_name, last_name, mother, or father is required"}

    # Parent-mode with no explicit name: infer last name from parent to anchor the search.
    # Without a name param, Ancestry returns 300k+ noise results ignoring location filters.
    if not name_param and (mother or father):
        parent_name = (mother or father).strip()
        parts = parent_name.split()
        if len(parts) >= 2:
            inferred_last = parts[-1]
            name_param = _build_name_param("", inferred_last)  # "Hayes"
            name_x = "0_1"  # any first + exact last

    params: dict = {
        "count": str(count),
        "name_x": name_x,
        "searchMode": "advanced",
    }
    if name_param:
        params["name"] = name_param
    if offset > 0:
        # Ancestry paginates via pg= (1-based page number), not byte offsets.
        # pg=1 is the default (omitted); pg=2 fetches results count+1 through 2*count, etc.
        page_num = (offset // count) + 1
        params["pg"] = str(page_num)
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

    # Collection-specific search is much more precise than global search
    url = f"{BASE_URL}/search/collections/{collection_id}/" if collection_id else SEARCH_URL

    http = _make_session()
    try:
        resp = http.get(url, params=params, headers=_HEADERS, timeout=30, verify=False)
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
    Different collections use different label names — try multiple variants.
    """
    fields_by_label: dict[str, dict] = {}
    for f in item.get("fields", []):
        label = f.get("label", "").strip()
        if label:
            fields_by_label[label] = f

    def _field_text(*labels: str) -> str:
        for label in labels:
            f = fields_by_label.get(label, {})
            if f and not f.get("veiled"):
                val = _strip(f.get("text") or "")
                if val:
                    return val
        return ""

    def _field_date(*labels: str) -> str:
        for label in labels:
            f = fields_by_label.get(label, {})
            if f and not f.get("veiled"):
                val = (f.get("date") or "").strip() or _strip(f.get("text") or "")
                if val:
                    return val
        return ""

    def _field_place(*labels: str) -> str:
        for label in labels:
            f = fields_by_label.get(label, {})
            if f and not f.get("veiled"):
                val = (f.get("place") or "").strip() or _strip(f.get("text") or "")
                if val:
                    return val
        return ""

    # Parents
    parents = []
    for label in ("Father", "Mother", "Parent"):
        name = _field_text(label)
        if name:
            parents.append(name)

    # Children — Ancestry uses "Child", "Child 1", "Child 2", or "Relatives"
    children = []
    relatives_raw = _field_text("Relatives", "Child")
    if relatives_raw:
        children = [c.strip() for c in re.split(r"[\n,;]+", relatives_raw) if c.strip()]
    else:
        # numbered Child 1, Child 2, ...
        for label in fields_by_label:
            if "Child" in label:
                val = _field_text(label)
                if val:
                    children.append(val)

    # Spouse
    spouse = _field_text("Spouse", "Husband", "Wife", "Spouse/Partner")

    record_url = item.get("recordUrl") or ""
    if record_url and not record_url.startswith("http"):
        record_url = f"{BASE_URL}{record_url}"
    # Census and some other collections don't include recordUrl in search results.
    # Construct the canonical URL from collection_id + record_id so it's always usable.
    if not record_url:
        coll = item.get("collectionId") or ""
        rid  = item.get("recordId") or ""
        if coll and rid:
            record_url = f"{BASE_URL}/search/collections/{coll}/records/{rid}"

    return {
        "record_id":      item.get("recordId") or "",
        "collection_id":  item.get("collectionId") or "",
        "record_type":    item.get("primaryCategory") or item.get("collectionTitle") or "other",
        "collection":     item.get("collectionTitle") or "",
        "person_name":    _field_text("Name") or _strip(item.get("nameField", {}).get("text") or ""),
        "dob":            _field_date("Birth", "Birth Date", "Birth Year"),
        "dod":            _field_date("Death", "Death Date", "Publication Date"),
        "birth_location": _field_place("Birth", "Birthplace", "Birth Place"),
        "death_location": _field_place("Death", "Death Place", "Publication Place", "Residence Place"),
        "spouse_name":    spouse,
        "parents":        parents,
        "children":       children,
        "siblings":       [],
        "residence":      _field_text("Residence", "Residence Place", "Last Residence"),
        "source_url":     record_url,
        "confidence":     "high" if item.get("hasRecordViewRights") else "medium",
        "has_image":      bool(item.get("imageIds")),
        "viewable":       bool(item.get("hasRecordViewRights")),
    }


def _parse_record_page(html: str, url: str) -> dict:
    """
    Parse a single Ancestry record page (/search/collections/{id}/records/{id}).
    These pages use <th>Label</th><td>Value</td> pairs — not __PRELOADED_STATE__.
    """
    pairs = re.findall(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", html, re.DOTALL | re.IGNORECASE)
    data: dict[str, str] = {}
    links: dict[str, str] = {}
    for th, td in pairs:
        label = _strip(th)
        value = _strip(td)
        if label and value:
            data[label] = value
        # Capture navigation link for this cell before stripping HTML
        if label:
            href_m = re.search(r'href=["\']([^"\']+)["\']', td)
            if href_m:
                href = href_m.group(1)
                if not href.startswith("http"):
                    href = f"{BASE_URL}{href}"
                links[label] = href
            elif label == "Neighbors":
                # Census "View others on page" is a <button data-image-gid="IMAGE_ID:COLL_ID">
                # Construct a search URL to find all records on the same census sheet image.
                gid_m = re.search(r'data-image-gid=["\']([^"\']+)["\']', td)
                if gid_m:
                    raw_gid = gid_m.group(1)
                    img_id, _, coll_id = raw_gid.partition(":")
                    coll_path = f"/search/collections/{coll_id}/" if coll_id else "/search/"
                    links["Neighbors"] = f"{BASE_URL}{coll_path}?imageId={img_id}&count=50"

    # Children may be newline-separated under "Child" or "Relatives"
    raw_rel = data.get("Child") or data.get("Relatives") or ""
    children = [c.strip() for c in re.split(r"[\n,;]+", raw_rel) if c.strip()] if raw_rel else []

    parents = []
    for label in ("Father", "Mother", "Parent"):
        val = data.get(label)
        if val:
            parents.append(val)

    return {
        "record_id":      url,
        "collection_id":  "",
        "record_type":    "record",
        "collection":     data.get("Newspaper Title") or data.get("Collection") or "",
        "person_name":    data.get("Name") or "",
        "dob":            data.get("Birth Date") or data.get("Birth Year") or "",
        "dod":            data.get("Death Date") or data.get("Death Year") or data.get("Obituary Date") or "",
        "birth_location": data.get("Birth Place") or data.get("Birthplace") or data.get("Residence Place") or "",
        "death_location": data.get("Death Place") or data.get("Obituary Place") or data.get("Publication Place") or "",
        "spouse_name":    data.get("Spouse") or data.get("Husband") or data.get("Wife") or "",
        "parents":        parents,
        "children":       children,
        "siblings":       [],
        "residence":      data.get("Residence Place") or data.get("Last Residence") or "",
        "source_url":     url,
        "confidence":     "high",
        "has_image":      False,
        "viewable":       True,
        "_raw_fields":    data,
        "_links":         links,
    }


def get_household_members(record_url: str) -> dict:
    """
    Given any Ancestry census record URL, return all members of the same household.

    Strategy: Ancestry census record IDs are sequential within a census sheet.
    Walk backwards from the anchor record to find the head of household, then
    walk forward collecting all members until the sheet changes or a new head appears.

    This is the reliable way to find children not named in an obituary —
    census household members include all children living at home at census time.
    """
    if not sess.has_valid_session():
        return {"error": "no_session"}

    anchor = get_record(record_url)
    if anchor.get("error"):
        return anchor

    records = anchor.get("records", [])
    if not records:
        return {"error": "record_not_found", "records": []}

    r0 = records[0]
    raw0 = r0.get("_raw_fields", {})
    anchor_sheet = (
        raw0.get("Sheet Number")
        or raw0.get("Page Number")
        or ""
    )

    # Extract numeric record ID and collection ID from URL
    id_m   = re.search(r"/records/(\d+)", record_url)
    coll_m = re.search(r"/collections/(\d+)/", record_url)
    if not id_m or not coll_m:
        return {
            "error": "cannot_parse_url",
            "message": "URL must be /search/collections/{coll_id}/records/{record_id}",
            "records": [],
        }
    base_id   = int(id_m.group(1))
    coll_id   = coll_m.group(1)

    def _fetch(rid: int) -> dict | None:
        url = f"{BASE_URL}/search/collections/{coll_id}/records/{rid}"
        r = get_record(url)
        recs = r.get("records", [])
        return recs[0] if recs else None

    # Walk backwards to find the Head of this household (max 20 steps)
    head_id = base_id
    anchor_rel = raw0.get("Relation to Head of House", "").lower()
    if anchor_rel != "head":
        for delta in range(1, 21):
            rec = _fetch(base_id - delta)
            if rec is None:
                break
            raw = rec.get("_raw_fields", {})
            sheet = raw.get("Sheet Number") or raw.get("Page Number") or ""
            if anchor_sheet and sheet and sheet != anchor_sheet:
                break
            if (raw.get("Relation to Head of House") or "").lower() == "head":
                head_id = base_id - delta
                break

    # Walk forward from Head, collecting all members of this household
    members: list[dict] = []
    for delta in range(0, 20):
        rec = _fetch(head_id + delta)
        if rec is None:
            break
        raw = rec.get("_raw_fields", {})
        sheet = raw.get("Sheet Number") or raw.get("Page Number") or ""
        if anchor_sheet and sheet and sheet != anchor_sheet:
            break
        rel = raw.get("Relation to Head of House") or raw.get("Relationship") or ""
        # A new 'Head' entry means a new household — stop
        if delta > 0 and rel.lower() == "head":
            break
        members.append({**rec, "relationship_to_head": rel})

    return {
        "result_count": len(members),
        "returned": len(members),
        "records": members,
        "method": "sequential_scan",
        "sheet": anchor_sheet,
    }


def get_record(record_id: str) -> dict:
    """
    Fetch a specific Ancestry record by URL or ID.
    Handles two page types:
      - /search/collections/{cid}/records/{rid} — single record page (th/td parser)
      - search results pages — __PRELOADED_STATE__ parser
    """
    if not sess.has_valid_session():
        return {"error": "no_session"}

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

    html = resp.text

    # Single record page: no __PRELOADED_STATE__, uses th/td structure
    if "__PRELOADED_STATE__" not in html and "/records/" in url:
        record = _parse_record_page(html, url)
        if record.get("person_name"):
            return {"result_count": 1, "returned": 1, "records": [record]}
        return {"error": "parse_failed", "message": "Could not extract person data from record page", "records": []}

    return _parse_html(html, record_id)
