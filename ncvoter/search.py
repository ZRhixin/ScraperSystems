"""
NC State Board of Elections — Voter Registration Lookup
https://vt.ncsbe.gov/RegLkup/

Public search, no login required.
Key uses in heir tracing:
  1. Confirm a person is living (active registration) or removed (possibly deceased/moved)
  2. Find current MARRIED name — woman registered under her married surname
  3. Get current city/state/zip for service of process
  4. Confirm identity via NCID cross-reference

Flow: GET /RegLkup/ → extract __RequestVerificationToken → POST /RegLkup/ with
correct ASP.NET MVC field names → parse embedded JSON array from response HTML.

The site renders voter data server-side into a JS variable:
    var data = [{ VoterRegNum, CountyID, CountyName, FullName, NCID,
                  ResAddressCSZ, StatusLbl, StatusDesc }, ...]

StatusLbl: A=Active, I=Inactive, S=Suspended (all registered in NC)
           R=Removed, D=Denied (no longer active or moved)
"""
import re
import json

from curl_cffi import requests as cffi_requests

BASE_URL  = "https://vt.ncsbe.gov"
FORM_URL  = f"{BASE_URL}/RegLkup/"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS_GET = {
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent":      _UA,
}
_HEADERS_POST = {
    **_HEADERS_GET,
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin":       BASE_URL,
    "Referer":      FORM_URL,
}

# NC county name → SBOE SelectedCountyID value
_COUNTY_CODES: dict[str, str] = {
    "ALAMANCE": "1", "ALEXANDER": "2", "ALLEGHANY": "3", "ANSON": "4",
    "ASHE": "5", "AVERY": "6", "BEAUFORT": "7", "BERTIE": "8",
    "BLADEN": "9", "BRUNSWICK": "10", "BUNCOMBE": "11", "BURKE": "12",
    "CABARRUS": "13", "CALDWELL": "14", "CAMDEN": "15", "CARTERET": "16",
    "CASWELL": "17", "CATAWBA": "18", "CHATHAM": "19", "CHEROKEE": "20",
    "CHOWAN": "21", "CLAY": "22", "CLEVELAND": "23", "COLUMBUS": "24",
    "CRAVEN": "25", "CUMBERLAND": "26", "CURRITUCK": "27", "DARE": "28",
    "DAVIDSON": "29", "DAVIE": "30", "DUPLIN": "31", "DURHAM": "32",
    "EDGECOMBE": "33", "FORSYTH": "34", "FRANKLIN": "35", "GASTON": "36",
    "GATES": "37", "GRAHAM": "38", "GRANVILLE": "39", "GREENE": "40",
    "GUILFORD": "41", "HALIFAX": "42", "HARNETT": "43", "HAYWOOD": "44",
    "HENDERSON": "45", "HERTFORD": "46", "HOKE": "47", "HYDE": "48",
    "IREDELL": "49", "JACKSON": "50", "JOHNSTON": "51", "JONES": "52",
    "LEE": "53", "LENOIR": "54", "LINCOLN": "55", "MACON": "56",
    "MADISON": "57", "MARTIN": "58", "MCDOWELL": "59", "MECKLENBURG": "60",
    "MITCHELL": "61", "MONTGOMERY": "62", "MOORE": "63", "NASH": "64",
    "NEW HANOVER": "65", "NORTHAMPTON": "66", "ONSLOW": "67", "ORANGE": "68",
    "PAMLICO": "69", "PASQUOTANK": "70", "PENDER": "71", "PERQUIMANS": "72",
    "PERSON": "73", "PITT": "74", "POLK": "75", "RANDOLPH": "76",
    "RICHMOND": "77", "ROBESON": "78", "ROCKINGHAM": "79", "ROWAN": "80",
    "RUTHERFORD": "81", "SAMPSON": "82", "SCOTLAND": "83", "STANLY": "84",
    "STOKES": "85", "SURRY": "86", "SWAIN": "87", "TRANSYLVANIA": "88",
    "TYRRELL": "89", "UNION": "90", "VANCE": "91", "WAKE": "92",
    "WARREN": "93", "WASHINGTON": "94", "WATAUGA": "95", "WAYNE": "96",
    "WILKES": "97", "WILSON": "98", "YADKIN": "99", "YANCEY": "100",
}


def _extract_csrf(html: str) -> str:
    m = re.search(
        r'<input[^>]+name="__RequestVerificationToken"[^>]+value="([^"]+)"',
        html, re.IGNORECASE
    )
    return m.group(1) if m else ""


def _session() -> tuple[cffi_requests.Session, str]:
    s = cffi_requests.Session(impersonate="chrome124")
    csrf = ""
    try:
        r = s.get(FORM_URL, headers=_HEADERS_GET, timeout=20, verify=False)
        csrf = _extract_csrf(r.text)
    except Exception:
        pass
    return s, csrf


def lookup(
    last_name: str,
    first_name: str = "",
    middle_initial: str = "",
    birth_year: str = "",
    county: str = "",
    include_removed: bool = False,
) -> dict:
    """
    Search NC voter registration by name.

    Returns list of voter records:
      { ncid, voter_reg_num, name, county, city_state_zip,
        status, status_desc }

    status / status_desc:
      A → ACTIVE       (living in NC, registered)
      I → INACTIVE
      S → SUSPENDED
      R → REMOVED      (moved out of state or deceased)
      D → DENIED

    county: NC county name (e.g., "Wake") — empty = statewide.
    middle_initial: single character only.
    """
    if not last_name:
        return {"error": "last_name is required", "records": []}

    county_code = ""
    if county:
        county_code = _COUNTY_CODES.get(county.upper().strip(), "")

    mi = (middle_initial.strip() or "")[:1].upper()

    # ASP.NET MVC checkbox pattern: send both the checkbox value (true) and the
    # hidden fallback (false). For unchecked boxes, send only the hidden (false).
    form_data: list[tuple] = [
        ("FirstName",    first_name.strip().upper()),
        ("MiddleInitial", mi),
        ("LastName",     last_name.strip().upper()),
        ("BirthYear",    str(birth_year).strip() if birth_year else ""),
        ("SelectedCountyID", county_code),
        # Status[0] = Registered (A, I, S) — always include
        ("RegistrationStatusList[0].IsSelected", "true"),
        ("RegistrationStatusList[0].IsSelected", "false"),
        ("RegistrationStatusList[0].Value",       "A,I,S"),
        ("RegistrationStatusList[0].Name",        "Registered"),
    ]
    if include_removed:
        form_data.append(("RegistrationStatusList[1].IsSelected", "true"))
    form_data += [
        ("RegistrationStatusList[1].IsSelected", "false"),
        ("RegistrationStatusList[1].Value",       "R,D"),
        ("RegistrationStatusList[1].Name",        "Removed or Denied"),
        ("VoterRegNum", ""),
        ("CountyID",    ""),
    ]

    http, csrf = _session()
    if csrf:
        form_data.append(("__RequestVerificationToken", csrf))

    try:
        resp = http.post(
            FORM_URL,
            data=form_data,
            headers=_HEADERS_POST,
            timeout=30,
            verify=False,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:
        return {"error": str(exc), "records": []}

    records = _parse_response(resp.text)
    return {
        "search_name": f"{first_name} {last_name}".strip().upper(),
        "county":      county,
        "count":       len(records),
        "records":     records,
    }


def _parse_response(html: str) -> list[dict]:
    """
    Extract the server-rendered voter JSON array from the page HTML.

    The server embeds results as:
        var data = [{ VoterRegNum, CountyID, CountyName, FullName,
                      NCID, ResAddressCSZ, StatusLbl, StatusDesc }, ...]
    """
    # Greedy match of the whole JS array (may contain nested {})
    m = re.search(r"var data\s*=\s*(\[[^\]]*(?:\{[^\}]*\}[^\]]*)*\])\s*;", html)
    if not m:
        # Fallback: match anything between var data = [ ... ];
        m = re.search(r"var data\s*=\s*(\[.*?\])\s*;", html, re.DOTALL)
    if not m:
        return []

    try:
        raw = json.loads(m.group(1))
    except Exception:
        return []

    records = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        records.append({
            "ncid":          row.get("NCID", ""),
            "voter_reg_num": row.get("VoterRegNum", ""),
            "name":          row.get("FullName", ""),
            "county":        row.get("CountyName", ""),
            "city_state_zip": row.get("ResAddressCSZ", ""),
            "status":        row.get("StatusLbl", ""),
            "status_desc":   row.get("StatusDesc", ""),
        })
    return records
