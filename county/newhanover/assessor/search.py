"""
New Hanover County Assessor scraper.
https://etax.nhcgov.com/pt/

iasWorld Public Access platform by Tyler Technologies.
ASP.NET WebForms — requires __VIEWSTATE + __EVENTVALIDATION tokens per request.
DISCLAIMER=1 cookie required (set directly, no acceptance flow needed).

Three search modes:
  search_by_address(street_name, ...)
  search_by_owner(owner_name, ...)
  search_by_parcel(parcel_id, ...)
"""
from bs4 import BeautifulSoup
from curl_cffi import requests

BASE_URL = "https://etax.nhcgov.com/pt"
SEARCH_URL = f"{BASE_URL}/search/CommonSearch.aspx"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


def _new_session(mode: str) -> tuple:
    """GET the search page, set DISCLAIMER cookie, return (session, tokens)."""
    s = requests.Session(impersonate="chrome120")
    s.cookies.set("DISCLAIMER", "1", domain="etax.nhcgov.com")
    r = s.get(
        f"{SEARCH_URL}?mode={mode}",
        headers={"User-Agent": _UA},
        timeout=15,
    )
    soup = BeautifulSoup(r.text, "html.parser")
    return s, _extract_tokens(soup)


def _extract_tokens(soup) -> dict:
    tokens = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION"):
        el = soup.find("input", {"name": name})
        tokens[name] = el["value"] if el else ""
    return tokens


def _base_payload(tokens: dict, mode: str, page: int = 1, page_size: int = 15) -> dict:
    return {
        "ScriptManager1_TSM": "",
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": tokens["__VIEWSTATE"],
        "__VIEWSTATEGENERATOR": tokens.get("__VIEWSTATEGENERATOR", ""),
        "__EVENTVALIDATION": tokens["__EVENTVALIDATION"],
        "PageNum": "" if page == 1 else str(page),
        "SortBy": "PARID",
        "SortDir": " asc",
        "PageSize": str(page_size),
        "hdAction": "Search",
        "hdIndex": "",
        "sIndex": "-1",
        "hdListType": "PA",
        "hdJur": "",
        "hdSelectAllChecked": "false",
        "selSortBy": "PARID",
        "selSortDir": " asc",
        "selPageSize": str(page_size),
        "searchOptions$hdBeta": "",
        "btSearch": "",
        "RadWindow_NavigateUrl_ClientState": "",
        "mode": mode,
        "mask": "",
        "param1": "",
        "searchimmediate": "",
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def search_by_address(
    street_name: str,
    street_number: str = "",
    suffix: str = "",
    direction: str = "",
    page: int = 1,
    page_size: int = 25,
) -> list[dict]:
    """
    Search by street name (required). street_number, suffix, direction are optional.
    suffix defaults to *** (match all suffixes).
    direction: E, N, NE, S, SE, W or empty for all.
    """
    s, tokens = _new_session("ADDRESS")
    payload = _base_payload(tokens, "ADDRESS", page, page_size)
    payload.update({
        "inpNumber": street_number,
        "inpUnit": "",
        "inpStreet": street_name,
        "inpSuffix1": suffix,
        "inpAdrdir": direction,
    })
    r = s.post(
        f"{SEARCH_URL}?mode=ADDRESS",
        data=payload,
        headers={"User-Agent": _UA, "Referer": f"{SEARCH_URL}?mode=ADDRESS"},
        timeout=15,
    )
    return _parse_results(r.text)


def search_by_owner(
    owner_name: str,
    page: int = 1,
    page_size: int = 25,
) -> list[dict]:
    """
    Search by owner name (last name or full name).
    Partial matches supported (e.g. "Smith" returns all Smith owners).
    """
    s, tokens = _new_session("OWNER")
    payload = _base_payload(tokens, "OWNER", page, page_size)
    payload["inpOwner"] = owner_name
    r = s.post(
        f"{SEARCH_URL}?mode=OWNER",
        data=payload,
        headers={"User-Agent": _UA, "Referer": f"{SEARCH_URL}?mode=OWNER"},
        timeout=15,
    )
    return _parse_results(r.text)


def search_by_parcel(
    parcel_id: str,
    page: int = 1,
    page_size: int = 25,
) -> list[dict]:
    """
    Search by parcel ID (e.g. "R05720-031-010-000").
    Partial matches may work depending on server config.
    """
    s, tokens = _new_session("PARID")
    payload = _base_payload(tokens, "PARID", page, page_size)
    payload["inpParid"] = parcel_id
    r = s.post(
        f"{SEARCH_URL}?mode=PARID",
        data=payload,
        headers={"User-Agent": _UA, "Referer": f"{SEARCH_URL}?mode=PARID"},
        timeout=15,
    )
    return _parse_results(r.text)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr", class_="SearchResults")
    results = []
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 5:
            continue
        results.append({
            "parcel_id": tds[0].get_text(strip=True),
            "owner": tds[1].get_text(strip=True),
            "address": " ".join(tds[2].get_text().split()),
            "roll": tds[3].get_text(strip=True),
            "luc": tds[4].get_text(strip=True),
        })
    return results
