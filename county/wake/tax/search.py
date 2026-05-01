"""
Wake County Property Tax search scraper.
https://services.wake.gov/ptax/main/billing/

ASP.NET WebForms site — requires extracting __VIEWSTATE and __EVENTVALIDATION
tokens from the page before every POST.

Confirmed working:
  search_by_owner(last_name, first_name, middle_name, years, all_pages)

Pending verification (server rejects submitted values):
  search_by_account(account_number, years)   — account number format unknown
  search_by_business(business_name, years)   — silently fails, needs investigation

years: how many years of tax history to return (default 10)
all_pages: if True, triggers the "No Paging" postback to return all results at once
"""
import re

from bs4 import BeautifulSoup
from curl_cffi import requests

BASE_URL = "https://services.wake.gov/ptax/main/billing"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)
_POST_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://services.wake.gov",
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _new_session() -> requests.Session:
    return requests.Session(impersonate="chrome120")


def _extract_tokens(soup: BeautifulSoup) -> dict:
    tokens = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__SCROLLPOSITIONX",
                 "__SCROLLPOSITIONY", "__EVENTVALIDATION"):
        el = soup.find("input", {"name": name})
        tokens[name] = el["value"] if el else ""
    return tokens


def _search_url(search_by: str, last: str, first: str, middle: str, years: int) -> str:
    return (
        f"{BASE_URL}/default.aspx"
        f"?search={search_by}&yrs={years}&last={last}&first={first}&middle={middle}&cnt=0"
    )


# ---------------------------------------------------------------------------
# Search entry points
# ---------------------------------------------------------------------------

def search_by_owner(
    last_name: str,
    first_name: str = "",
    middle_name: str = "",
    years: int = 10,
    all_pages: bool = False,
) -> list[dict]:
    s = _new_session()
    page_url = _search_url("owner", last_name, first_name, middle_name, years)

    soup = BeautifulSoup(s.get(f"{BASE_URL}/default.aspx", timeout=15).text, "html.parser")
    tokens = _extract_tokens(soup)

    payload = {
        "__EVENTTARGET": "Search",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        **tokens,
        "ddlSearchBy": "owner",
        "ddlYears": str(years),
        "txtLast": last_name,
        "txtFirst": first_name,
        "txtMiddle": middle_name,
        "Search": "Search",
        "hidSearchBy": "owner",
        "hidDisplayMsg": "false",
    }
    headers = {**_POST_HEADERS, "Referer": page_url}
    r = s.post(page_url, data=payload, headers=headers, timeout=15)
    return _handle_results(s, r, all_pages)


def search_by_account(
    account_number: str,
    years: int = 10,
    all_pages: bool = False,
) -> list[dict]:
    s = _new_session()
    page_url = _search_url("acct", account_number, "", "", years)

    soup = BeautifulSoup(s.get(f"{BASE_URL}/default.aspx", timeout=15).text, "html.parser")
    tokens = _extract_tokens(soup)

    payload = {
        "__EVENTTARGET": "Search",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        **tokens,
        "ddlSearchBy": "acct",
        "ddlYears": str(years),
        "txtLast": account_number,
        "txtFirst": "",
        "txtMiddle": "",
        "Search": "Search",
        "hidSearchBy": "acct",
        "hidDisplayMsg": "false",
    }
    headers = {**_POST_HEADERS, "Referer": page_url}
    r = s.post(page_url, data=payload, headers=headers, timeout=15)
    return _handle_results(s, r, all_pages)


def search_by_business(
    business_name: str,
    years: int = 10,
    all_pages: bool = False,
) -> list[dict]:
    s = _new_session()
    page_url = _search_url("business", business_name, "", "", years)

    soup = BeautifulSoup(s.get(f"{BASE_URL}/default.aspx", timeout=15).text, "html.parser")
    tokens = _extract_tokens(soup)

    payload = {
        "__EVENTTARGET": "Search",
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        **tokens,
        "ddlSearchBy": "business",
        "ddlYears": str(years),
        "txtLast": business_name,
        "txtFirst": "",
        "txtMiddle": "",
        "Search": "Search",
        "hidSearchBy": "business",
        "hidDisplayMsg": "false",
    }
    headers = {**_POST_HEADERS, "Referer": page_url}
    r = s.post(page_url, data=payload, headers=headers, timeout=15)
    return _handle_results(s, r, all_pages)


# ---------------------------------------------------------------------------
# Result handling
# ---------------------------------------------------------------------------

def _handle_results(
    s: requests.Session,
    r: requests.Response,
    all_pages: bool,
) -> list[dict]:
    soup = BeautifulSoup(r.text, "html.parser")

    # Check for no results message
    no_results = soup.find(string=re.compile(r"No records matched", re.I))
    if no_results:
        return []

    if all_pages:
        # Trigger the "No Paging" postback to load all results at once
        tokens = _extract_tokens(soup)
        payload = {
            "__EVENTTARGET": "ctlNameBrowse",
            "__EVENTARGUMENT": "noPage-",
            "__LASTFOCUS": "",
            **tokens,
        }
        headers = {**_POST_HEADERS, "Referer": r.url}
        r = s.post(r.url, data=payload, headers=headers, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")

    return _parse_results(soup)


def _parse_results(soup: BeautifulSoup) -> list[dict]:
    rows = []
    for tr in soup.find_all("tr"):
        cells = [" ".join(c.get_text(" ", strip=True).split())
                 for c in tr.find_all("td", recursive=False)]
        if len(cells) < 8:
            continue
        # Data rows: index 0 is numeric line number, index 3 is 10-digit account
        if not cells[0].isdigit():
            continue
        if not re.match(r"^\d{10}$", cells[3]):
            continue
        rows.append({
            "name": cells[2],
            "account_number": cells[3],
            "year": cells[4],
            "type": cells[5],
            "description": cells[6],
            "amount_due": cells[7],
        })
    return rows
