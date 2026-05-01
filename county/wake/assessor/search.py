"""
Wake County Real Estate / Assessor scraper.
https://services.wake.gov/realestate/

Supports four search modes:
  search_by_owner(last_name, first_name)
  search_by_address(street_name, street_number)
  search_by_id(real_estate_id)
  search_by_pin(map, sheet, block, lot)

Each returns a list of summary dicts.
Use get_account(account_id) to fetch full detail for a specific property.
"""
import re

from bs4 import BeautifulSoup
from curl_cffi import requests

BASE_URL = "https://services.wake.gov/realestate"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://services.wake.gov",
    "Referer": f"{BASE_URL}/Search.asp",
}


def _new_session() -> requests.Session:
    s = requests.Session(impersonate="chrome120")
    s.get(f"{BASE_URL}/Search.asp", headers={"User-Agent": _UA}, timeout=15)
    return s


def _post_headers() -> dict:
    return {**_HEADERS, "Content-Type": "application/x-www-form-urlencoded"}


# ---------------------------------------------------------------------------
# Search entry points
# ---------------------------------------------------------------------------

def search_by_owner(
    last_name: str,
    first_name: str = "",
    fetch_details: bool = False,
) -> list[dict]:
    s = _new_session()
    payload = {"owner1": last_name, "owner2": first_name, "stype": "owner"}
    r = s.post(f"{BASE_URL}/DoSearchByOwner.asp", data=payload, headers=_post_headers(), timeout=15)
    results = _parse_owner_list(r.text)
    if fetch_details:
        for item in results:
            item.update(get_account(item["account_id"], session=s))
    return results


def search_by_address(
    street_name: str,
    street_number: str = "",
    fetch_details: bool = False,
) -> list[dict]:
    s = _new_session()
    payload = {"stname": street_name, "stnum": street_number, "stype": "addr"}
    r = s.post(f"{BASE_URL}/DoSearchByAddr.asp", data=payload, headers=_post_headers(), timeout=15)
    results = _parse_address_list(r.text)
    if fetch_details:
        for item in results:
            item.update(get_account(item["account_id"], session=s))
    return results


def search_by_id(real_estate_id: str, fetch_details: bool = False) -> list[dict]:
    s = _new_session()
    rid = str(real_estate_id).zfill(7)
    payload = {"id": rid, "stype": "acct"}
    r = s.post(f"{BASE_URL}/DoSearchByID.asp", data=payload, headers=_post_headers(), timeout=15)
    # Server redirects directly to Account.asp when exactly one match is found
    if "Account.asp" in r.url:
        return [_parse_account(r.text)]
    return _parse_owner_list(r.text)


def search_by_pin(
    map_num: str,
    sheet: str = "",
    block: str = "",
    lot: str = "",
    fetch_details: bool = False,
) -> list[dict]:
    s = _new_session()
    payload = {"map": map_num, "sheet": sheet, "block": block, "lot": lot, "stype": "pin"}
    r = s.post(f"{BASE_URL}/DoSearchByPin.asp", data=payload, headers=_post_headers(), timeout=15)
    results = _parse_pin_list(r.text)
    if fetch_details:
        for item in results:
            item.update(get_account(item["account_id"], session=s))
    return results


# ---------------------------------------------------------------------------
# Detail fetch
# ---------------------------------------------------------------------------

def get_account(account_id: str, session: requests.Session | None = None) -> dict:
    s = session or _new_session()
    rid = str(account_id).zfill(7)
    r = s.get(f"{BASE_URL}/Account.asp?id={rid}", headers={"User-Agent": _UA}, timeout=15)
    return _parse_account(r.text)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _find_header_table(soup: BeautifulSoup, marker: str):
    """Return (table, header_row_index) for the first table containing marker in a td."""
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        for i, tr in enumerate(trs):
            if marker in [c.get_text(strip=True) for c in tr.find_all("td")]:
                return table, i
    return None, None


def _parse_owner_list(html: str) -> list[dict]:
    # Columns: Line, spacer, Account, spacer, Owner, Location Address, City, Description
    soup = BeautifulSoup(html, "html.parser")
    table, header_idx = _find_header_table(soup, "Account")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr")[header_idx + 1:]:
        texts = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(texts) < 8 or not texts[2].isdigit():
            continue
        rows.append({
            "account_id": texts[2],
            "owner": texts[4],
            "location_address": texts[5],
            "city": texts[6],
            "property_description": texts[7],
        })
    return rows


def _parse_address_list(html: str) -> list[dict]:
    # Columns: Line, Account, St Num, St Misc, Pfx, Street Name, Type, Sfx, ETJ, Owner
    soup = BeautifulSoup(html, "html.parser")
    table, header_idx = _find_header_table(soup, "St Num")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr")[header_idx + 1:]:
        texts = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(texts) < 10 or not texts[1].isdigit():
            continue
        address_parts = filter(None, [texts[2], texts[4], texts[5], texts[6], texts[7]])
        rows.append({
            "account_id": texts[1].zfill(7),
            "owner": texts[9],
            "location_address": " ".join(address_parts),
            "city": "",
            "property_description": "",
        })
    return rows


def _parse_pin_list(html: str) -> list[dict]:
    # Columns: Line, spacer, Map, PIN Number, Account, spacer, Owner, Property Description
    soup = BeautifulSoup(html, "html.parser")
    table, header_idx = _find_header_table(soup, "PIN Number")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr")[header_idx + 1:]:
        texts = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(texts) < 8 or not texts[4].isdigit():
            continue
        rows.append({
            "account_id": texts[4].zfill(7),
            "pin": texts[3],
            "owner": texts[6],
            "location_address": "",
            "city": "",
            "property_description": texts[7],
        })
    return rows


_ACCOUNT_LABELS = {
    "Real Estate ID", "PIN #", "Property Owner", "Owner's Mailing Address",
    "Property Location Address", "Zoning", "Land Class", "City", "Township",
    "Acreage", "Heated Area", "Deed Date", "Book & Page", "Pkg Sale Date",
    "Pkg Sale Price", "Land Value Assessed", "Bldg. Value Assessed",
    "Total Value Assessed*", "Permit Date", "Permit #", "Assessed Value",
    "Tax Relief", "Land Use Value", "Use Value Deferment", "Historic Deferment",
    "Total Deferred Value", "Use/Hist/Tax Relief Assessed", "Revenue Stamps",
    "Land Sale Date", "Land Sale Price", "Improvement Summary",
}


def _parse_account(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="|", strip=True)

    def _val(label: str) -> str:
        m = re.search(rf"{re.escape(label)}\s*\|\s*([^|]+)", text, re.IGNORECASE)
        if not m:
            return ""
        value = m.group(1).strip()
        # Reject known labels or the legal disclaimer (starts with *)
        if value in _ACCOUNT_LABELS or value.startswith("*"):
            return ""
        return value

    return {
        "account_id": _val("Real Estate ID"),
        "pin": _val("PIN #"),
        "owner": _val("Property Owner"),
        "mailing_address": _val("Owner's Mailing Address"),
        "location_address": _val("Property Location Address"),
        "zoning": _val("Zoning"),
        "land_class": _val("Land Class"),
        "city": _val("City"),
        "township": _val("Township"),
        "acreage": _val("Acreage"),
        "heated_area_sqft": _val("Heated Area"),
        "deed_date": _val("Deed Date"),
        "deed_book_page": _val("Book & Page"),
        "sale_date": _val("Pkg Sale Date"),
        "sale_price": _val("Pkg Sale Price"),
        "land_value": _val("Land Value Assessed"),
        "building_value": _val("Bldg. Value Assessed"),
        "total_value": _val("Total Value Assessed*"),
        "permit_date": _val("Permit Date"),
        "permit_number": _val("Permit #"),
    }
