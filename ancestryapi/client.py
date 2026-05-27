"""
Ancestry.com client — public API used by server.py and n8n tools.

Session management is automatic: if no valid cookies are saved, auto_login
will launch a headless Chromium browser to sign in using ANCESTRY_EMAIL /
ANCESTRY_PASSWORD from .env.  Cookies are reused for days until Ancestry
invalidates the session.
"""
import json

from . import session as sess
from .search import search_person as _search, get_record as _record, get_household_members as _household


def _require_session() -> dict | None:
    """Ensure a valid session exists. Returns error dict on failure, None on success."""
    if sess.has_valid_session():
        return None

    from .auto_login import login
    ok = login(headless=False)
    if not ok:
        return {
            "error": "login_failed",
            "message": (
                "Auto-login failed. Check ANCESTRY_EMAIL / ANCESTRY_PASSWORD in .env, "
                "or export cookies manually: python -m ancestryapi.extract_cookies"
            ),
        }
    return None


def search(
    first_name: str = "",
    last_name: str = "",
    birth_year: str = "",
    death_year: str = "",
    birth_year_range: int = 3,
    death_year_range: int = 3,
    state: str = "NC",
    birth_location: str = "",
    death_location: str = "",
    gender: str = "",
    spouse: str = "",
    father: str = "",
    mother: str = "",
    name_x: str = "1_1",
    count: int = 50,
    collection_id: str = "",
) -> dict:
    """
    Search Ancestry for a person.
    Returns { result_count, records: [...] } or { error, message }.
    Auto-logs in if no valid session exists.
    """
    if not first_name and not last_name and not mother and not father:
        return {"error": "bad_request", "message": "first_name, last_name, mother, or father is required"}

    err = _require_session()
    if err:
        return err

    return _search(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        birth_year=str(birth_year).strip() if birth_year else "",
        death_year=str(death_year).strip() if death_year else "",
        birth_year_range=birth_year_range,
        death_year_range=death_year_range,
        state=state.strip(),
        birth_location=birth_location.strip(),
        death_location=death_location.strip(),
        gender=gender.strip(),
        spouse=spouse.strip(),
        father=father.strip(),
        mother=mother.strip(),
        name_x=name_x.strip(),
        count=count,
        collection_id=collection_id.strip(),
    )


def search_paged(
    max_pages: int = 3,
    page_size: int = 20,
    **kwargs,
) -> dict:
    """
    Paginate through Ancestry search results, up to max_pages pages.
    Stops early if a page returns fewer records than page_size (last page).
    Returns combined { result_count, returned, records }.
    """
    err = _require_session()
    if err:
        return err

    all_records = []
    result_count = 0

    for page in range(max_pages):
        offset = page * page_size
        result = _search(offset=offset, count=page_size, **kwargs)
        if "error" in result:
            if page == 0:
                return result
            break
        result_count = result.get("result_count", result_count)
        page_records = result.get("records", [])
        all_records.extend(page_records)
        if len(page_records) < page_size:
            break

    return {
        "result_count": result_count,
        "returned": len(all_records),
        "records": all_records,
    }


def record_detail(record_id: str) -> dict:
    """
    Fetch a specific Ancestry record by its ID or full URL.
    Returns the full record data or { error, message }.
    Auto-logs in if no valid session exists.
    """
    if not record_id:
        return {"error": "bad_request", "message": "record_id is required"}

    err = _require_session()
    if err:
        return err

    return _record(record_id.strip())


def household_members(record_url: str) -> dict:
    """
    Given a census record URL, return all members of the same household.
    Uses the 'View others on page' link embedded in the census record page.
    """
    if not record_url:
        return {"error": "bad_request", "message": "record_url is required"}
    err = _require_session()
    if err:
        return err
    return _household(record_url.strip())


def session_status() -> dict:
    from .search import SEARCH_URL
    return {
        "configured": bool(SEARCH_URL),
        "session_summary": sess.cookies_summary(),
        "has_valid_session": sess.has_valid_session(),
    }


if __name__ == "__main__":
    print("[*] Session status:", json.dumps(session_status(), indent=2))

    if not sess.has_valid_session():
        print("[*] No session found — attempting auto-login...")
        from .auto_login import login
        ok = login(headless=True)
        if not ok:
            print("[!] Auto-login failed. Check credentials in .env")
            import sys; sys.exit(1)

    print("[*] Testing search for Lydia Hayes, NC...")
    result = search(first_name="Lydia", last_name="Hayes", state="NC")
    print(json.dumps(result, indent=2))
