"""
Wake County Register of Deeds scraper.
https://rodrecords.wake.gov/

Tyler Technologies Self-Service platform — Java backend (JSESSIONID).
Two-step search flow: POST validates + returns page count, GET fetches results HTML.
Optional detail fetch per document via /web/document/DOCC###### endpoint.

Search types:
  search_by_name(surname, ...)          — grantor, grantee, or both
  search_by_document(doc_number)        — exact document number lookup
  search_by_book_page(book, page)       — direct book/page lookup
  download_document_pdf(doc_id)         — download raw PDF bytes for a document
"""
import re
from bs4 import BeautifulSoup
from curl_cffi import requests

BASE_URL = "https://rodrecords.wake.gov"
SEARCH_ID = "DOCSEARCH341S2"
SEARCH_URL = f"{BASE_URL}/web/searchPost/{SEARCH_ID}"
RESULTS_URL = f"{BASE_URL}/web/searchResults/{SEARCH_ID}"
DOCUMENT_URL = f"{BASE_URL}/web/document"
SESSION_URL = f"{BASE_URL}/web/search/{SEARCH_ID}"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


def _new_session() -> requests.Session:
    s = requests.Session(impersonate="chrome120")
    s.cookies.set("disclaimerAccepted", "true", domain="rodrecords.wake.gov")
    s.get(SESSION_URL, headers={"User-Agent": _UA}, timeout=15)
    return s


def _base_payload() -> dict:
    return {
        "field_BookPageID_DOT_Volume": "",
        "field_BookPageID_DOT_Page": "",
        "field_RecordingDateID_DOT_StartDate": "",
        "field_RecordingDateID_DOT_EndDate": "",
        "field_BothNamesID_DOT_Human": "",
        "field_BothNamesID_DOT_Surname": "",
        "field_BothNamesID_DOT_Name": "",
        "field_BothNamesID_DOT_Suffix": "",
        "field_GrantorID_DOT_Soundex": "",
        "field_GrantorID_DOT_Human": "",
        "field_GrantorID_DOT_Surname": "",
        "field_GrantorID_DOT_Name": "",
        "field_GrantorID_DOT_Suffix": "",
        "field_GranteeID_DOT_Soundex": "",
        "field_GranteeID_DOT_Human": "",
        "field_GranteeID_DOT_Surname": "",
        "field_GranteeID_DOT_Name": "",
        "field_GranteeID_DOT_Suffix": "",
        "field_LegalRemarksID-containsInput": "Contains Any",
        "field_LegalRemarksID": "",
        "field_DocumentNumberID": "",
        "field_selfservice_documentTypes-containsInput": "Contains Any",
        "field_selfservice_documentTypes": "",
        "field_UseAdvancedSearch": "",
    }


def _search_headers() -> dict:
    return {
        "User-Agent": _UA,
        "Ajaxrequest": "true",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": SESSION_URL,
        "Origin": BASE_URL,
    }


def _results_headers() -> dict:
    return {
        "User-Agent": _UA,
        "Ajaxrequest": "true",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
        "Referer": SESSION_URL,
    }


def _do_search(s: requests.Session, payload: dict, page: int, fetch_details: bool) -> list[dict]:
    r = s.post(SEARCH_URL, data=payload, headers=_search_headers(), timeout=15)
    info = r.json()

    if info.get("validationMessages"):
        return []

    total_pages = int(info.get("totalPages", 1))
    pages_to_fetch = range(1, total_pages + 1) if page == 0 else [page]

    results = []
    for p in pages_to_fetch:
        import time
        r2 = s.get(
            f"{RESULTS_URL}?page={p}&_={int(time.time() * 1000)}",
            headers=_results_headers(),
            timeout=15,
        )
        rows = _parse_results(r2.text)
        if fetch_details:
            for row in rows:
                if row.get("doc_id"):
                    detail = get_document(s, row["doc_id"])
                    row.update(detail)
        results.extend(rows)

    return results


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def search_by_name(
    surname: str,
    first_name: str = "",
    role: str = "both",
    start_date: str = "",
    end_date: str = "",
    doc_types: list[str] | None = None,
    page: int = 1,
    fetch_details: bool = False,
) -> list[dict]:
    """
    Search by person name.
    role: "grantor", "grantee", or "both" (default)
    doc_types: filter list e.g. ["DEED", "QUIT CLAIM DEED"]
    page: specific page number, or 0 to fetch all pages
    fetch_details: if True, fetch full detail for each result
    """
    s = _new_session()
    payload = _base_payload()

    role = role.lower()
    if role == "grantor":
        payload["field_GrantorID_DOT_Human"] = "h"
        payload["field_GrantorID_DOT_Surname"] = surname
        payload["field_GrantorID_DOT_Name"] = first_name
    elif role == "grantee":
        payload["field_GranteeID_DOT_Human"] = "h"
        payload["field_GranteeID_DOT_Surname"] = surname
        payload["field_GranteeID_DOT_Name"] = first_name
    else:
        payload["field_BothNamesID_DOT_Human"] = "h"
        payload["field_BothNamesID_DOT_Surname"] = surname
        payload["field_BothNamesID_DOT_Name"] = first_name

    if start_date:
        payload["field_RecordingDateID_DOT_StartDate"] = start_date
    if end_date:
        payload["field_RecordingDateID_DOT_EndDate"] = end_date
    if doc_types:
        payload["field_selfservice_documentTypes"] = "|".join(doc_types)

    return _do_search(s, payload, page, fetch_details)


def search_by_document(doc_number: str, fetch_details: bool = False) -> list[dict]:
    """
    Search by document number (e.g. "004714-00624").
    """
    s = _new_session()
    payload = _base_payload()
    payload["field_DocumentNumberID"] = doc_number
    return _do_search(s, payload, 1, fetch_details)


def search_by_book_page(book: str, page: str, fetch_details: bool = False) -> list[dict]:
    """
    Search by book and page number directly.
    This is Phase A's primary lookup — the appraiser gives book/page refs.
    """
    s = _new_session()
    payload = _base_payload()
    payload["field_BookPageID_DOT_Volume"] = str(book).strip()
    payload["field_BookPageID_DOT_Page"] = str(page).strip()
    return _do_search(s, payload, 1, fetch_details)


def download_document_pdf(doc_id: str, s: requests.Session | None = None) -> bytes:
    """
    Download the raw PDF bytes for a document.

    Flow (from Burp capture):
      1. GET /web/document/{doc_id} — detail page HTML contains the servepdf path
      2. GET /web/document/servepdf/SCALED-{doc_id}.1.pdf/{filename}?index=1 — actual PDF

    Returns raw PDF bytes.
    Raises ValueError if no PDF link is found on the detail page.
    """
    if s is None:
        s = _new_session()

    # Step 1: fetch detail page to extract the PDF filename
    detail_url = f"{DOCUMENT_URL}/{doc_id}?search={SEARCH_ID}"
    r = s.get(detail_url, headers={"User-Agent": _UA, "Referer": SESSION_URL}, timeout=15)
    r.raise_for_status()

    # The detail page has a div with data-image-name attribute:
    # <div data-pdf-base-url="/web/document-image-pdfjs/DOCC100471725"
    #      data-image-name="006511-00265" data-index="1" ...>
    # Actual PDF URL: /web/document/servepdf/SCALED-{doc_id}.1.pdf/{image_name}.pdf?index=1
    match = re.search(r'data-image-name="([^"]+)"', r.text)
    if not match:
        raise ValueError(f"No data-image-name found in detail page for {doc_id}")
    image_name = match.group(1)    # e.g. 006511-00265

    index_match = re.search(r'data-index="([^"]+)"', r.text)
    index = index_match.group(1) if index_match else "1"

    # Step 2: download the actual PDF
    # URL pattern from viewer HTML data-href attribute:
    # /web/document-image-pdf/{doc_id}//{image_name}-{index}.pdf?index={index}
    pdf_url = f"{BASE_URL}/web/document-image-pdf/{doc_id}//{image_name}-{index}.pdf?index={index}"
    pdf_resp = s.get(
        pdf_url,
        headers={"Referer": detail_url},
        timeout=30,
    )
    pdf_resp.raise_for_status()
    return pdf_resp.content, pdf_url


def get_document(s: requests.Session | None, doc_id: str) -> dict:
    """
    Fetch full detail for a specific document by its DOCC ID.
    """
    if s is None:
        s = _new_session()
    r = s.get(
        f"{DOCUMENT_URL}/{doc_id}?search={SEARCH_ID}",
        headers={"User-Agent": _UA, "Referer": SESSION_URL},
        timeout=15,
    )
    return _parse_detail(r.text)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_results(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for row in soup.find_all("li", class_="ss-search-row"):
        doc_id = row.get("data-documentid", "")
        result = {"doc_id": doc_id}

        # Document number, book/page, recording date are all in <h1>
        h1 = row.find("h1")
        if h1:
            h1_text = " ".join(h1.get_text(separator=" ").split())

            doc_num = re.search(r'\b(\d+-\d+)\b', h1_text)
            if doc_num:
                result["document_number"] = doc_num.group(1)

            date = re.search(r'(\d{2}/\d{2}/\d{4})', h1_text)
            if date:
                result["recording_date"] = date.group(1)

            book_pages = re.findall(r'B:\s*(\d+)\s*P:\s*(\d+)', h1_text)
            if book_pages:
                result["book"] = book_pages[0][0]
                result["page"] = book_pages[0][1]

        # Document type, grantor, grantee from searchResultFourColumn divs
        for col in row.find_all("div", class_="searchResultFourColumn"):
            lis = col.find_all("li")
            if len(lis) < 2:
                continue
            label = lis[0].get_text(strip=True)
            value_b = lis[1].find("b")
            value = value_b.get_text(strip=True) if value_b else lis[1].get_text(strip=True)

            if "Document Type" in label:
                result["doc_type"] = value
            elif "Grantor" in label:
                result["grantor"] = value
            elif "Grantee" in label:
                result["grantee"] = value

        results.append(result)

    return results


def _parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    result = {}

    def _get_field(label: str) -> str:
        strong = soup.find("strong", string=re.compile(label, re.IGNORECASE))
        if strong:
            parent = strong.find_parent("div")
            if parent:
                sibling = parent.find_next_sibling("div")
                if sibling:
                    return sibling.get_text(strip=True)
        return ""

    result["document_number"] = _get_field("Document Number")
    result["recording_date"] = _get_field("Recording Date").replace(" 12:00:00 AM", "")
    result["doc_type"] = _get_field("Old Document Type") or _get_field("Document Type")
    result["num_pages"] = _get_field("Number Pages")

    # Book/Page
    book_table = soup.find("table", class_=lambda c: c and "ui-responsive" in c and "doc-viewer" not in c)
    if book_table:
        rows = book_table.find_all("tr")
        if rows:
            tds = rows[0].find_all("td")
            if len(tds) >= 2:
                result["book"] = tds[0].get_text(strip=True)
                result["page"] = tds[1].get_text(strip=True)

    # Grantor / Grantee
    grantor_div = soup.find("strong", string=re.compile("Grantor", re.IGNORECASE))
    if grantor_div:
        parent = grantor_div.find_parent("div")
        if parent:
            sib = parent.find_next_sibling("div")
            if sib:
                result["grantor"] = sib.get_text(strip=True)

    grantee_div = soup.find("strong", string=re.compile("Grantee", re.IGNORECASE))
    if grantee_div:
        parent = grantee_div.find_parent("div")
        if parent:
            sib = parent.find_next_sibling("div")
            if sib:
                items = sib.find_all("li")
                if items:
                    result["grantee"] = [li.get_text(strip=True) for li in items]
                else:
                    result["grantee"] = [sib.get_text(strip=True)]

    # Legal description
    legal_section = soup.find("li", attrs={"aria-level": "1"}, string=re.compile("Legal", re.IGNORECASE))
    if not legal_section:
        for li in soup.find_all("li", class_="ui-li-divider"):
            if "Legal" in li.get_text():
                legal_section = li
                break
    if legal_section:
        parent_ul = legal_section.find_parent("ul")
        if parent_ul:
            content_li = parent_ul.find("li", class_=lambda c: c and "ui-li-static" in c)
            if content_li:
                result["legal"] = " ".join(content_li.get_text().split())

    return result
