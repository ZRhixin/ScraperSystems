"""
Buncombe County Assessor scraper.
https://prc-buncombe.spatialest.com/

Same Spatialest platform as Mecklenburg — modern Laravel REST API.
Requires CSRF token from page meta tag + session cookies.

Two-step flow:
  1. suggestions(term) — fast autocomplete, returns owner name + owner_id
  2. search(term)      — full property search, returns address, value, parcel, owner

Search matches against owner name, address, or parcel number.
Supports pagination via page/limit parameters.
"""
from bs4 import BeautifulSoup
from curl_cffi import requests

BASE_URL = "https://prc-buncombe.spatialest.com"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


def _new_session() -> tuple[requests.Session, str]:
    """Returns (session, csrf_token). Session already has cookies from the page load."""
    s = requests.Session(impersonate="chrome120")
    r = s.get(f"{BASE_URL}/", headers={"User-Agent": _UA}, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    meta = soup.find("meta", {"name": "csrf-token"})
    csrf = meta["content"] if meta else ""
    return s, csrf


def _api_headers(csrf: str) -> dict:
    return {
        "X-Csrf-Token": csrf,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/",
        "User-Agent": _UA,
    }


def _debug(term: str, page: int = 1) -> dict:
    return {
        "currentURL": f"{BASE_URL}/#/search/?term={term}&page={page}",
        "previousURL": "",
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def suggestions(term: str) -> list[dict]:
    """
    Autocomplete suggestions for a search term.
    Returns list of {"owner_id": str, "name": str}.
    """
    s, csrf = _new_session()
    payload = {"filters": {"term": term}, "debug": _debug(term)}
    r = s.post(
        f"{BASE_URL}/api/v2/search/suggestions",
        json=payload,
        headers=_api_headers(csrf),
        timeout=15,
    )
    data = r.json()
    if not data.get("success"):
        return []
    return [
        {"owner_id": item["id"], "name": item["suggest"]}
        for item in data.get("suggestions", [])
    ]


def search(term: str, page: int = 1, limit: int = 21) -> list[dict]:
    """
    Search properties by owner name, address, or parcel number.
    Returns list of parsed property dicts.
    """
    s, csrf = _new_session()
    payload = {
        "filters": {"term": term, "page": str(page)},
        "page": str(page),
        "limit": limit,
        "debug": _debug(term, page),
    }
    r = s.post(
        f"{BASE_URL}/api/v2/search",
        json=payload,
        headers=_api_headers(csrf),
        timeout=15,
    )
    data = r.json()
    return [_parse_result(item) for item in data.get("results", [])]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_result(item: dict) -> dict:
    display = {d["id"]: d["value"] for d in item.get("display", [])}
    return {
        "parcel_id": item.get("order_all_parcels_ParcelID", ""),
        "internal_id": item.get("ParcelIdentifier", ""),
        "address": display.get("location_address", ""),
        "owner": display.get("Owner1", ""),
        "appraised_value": display.get("PublicTotalMarketValue", ""),
        "latitude": item.get("cty", ""),
        "longitude": item.get("ctx", ""),
    }
