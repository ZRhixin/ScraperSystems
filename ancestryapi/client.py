"""
Ancestry.com client — public API used by server.py and n8n tools.

Session management is automatic: if no valid cookies are saved, auto_login
will launch a headless Chromium browser to sign in using ANCESTRY_EMAIL /
ANCESTRY_PASSWORD from .env.  Cookies are reused for days until Ancestry
invalidates the session.
"""
import json

from . import session as sess
from .search import search_person as _search, get_record as _record


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
    state: str = "NC",
) -> dict:
    """
    Search Ancestry for a person.
    Returns { result_count, records: [...] } or { error, message }.
    Auto-logs in if no valid session exists.
    """
    if not first_name and not last_name:
        return {"error": "bad_request", "message": "first_name or last_name is required"}

    err = _require_session()
    if err:
        return err

    return _search(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        birth_year=str(birth_year).strip() if birth_year else "",
        death_year=str(death_year).strip() if death_year else "",
        state=state.strip(),
    )


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
