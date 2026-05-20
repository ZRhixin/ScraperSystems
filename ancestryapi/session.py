"""
Cookie-based session management for Ancestry.com.
Ancestry uses long-lived browser cookies — no JWT rotation needed.
Cookies expire when Ancestry invalidates the session (~7–30 days).
"""
import json
import time
from pathlib import Path

COOKIES_FILE = Path(__file__).parent / "cookies.json"

# Key cookies Ancestry sets on login:
#   ANCSESSIONID  — main session identifier (long-lived)
#   ATT / ANCATT  — long-lived auth token (same value, different names)
#   SecureATT     — short-lived JWT (30 min) — refreshed by Ancestry automatically in browser
#   cf_clearance  — Cloudflare challenge clearance (~1hr) — must be re-exported when stale
#   ANCUUID       — persistent user identifier
_REQUIRED = ("ANCSESSIONID", "ATT")


def save_cookies(cookies: dict) -> None:
    """Persist cookies dict to disk (call after extracting from browser/DevTools)."""
    data = {
        "cookies": cookies,
        "saved_at": time.time(),
    }
    COOKIES_FILE.write_text(json.dumps(data, indent=2))
    print(f"[+] Saved {len(cookies)} cookies to {COOKIES_FILE}")


def load_cookies() -> dict:
    """Return stored cookies dict, or {} if not saved yet."""
    if not COOKIES_FILE.exists():
        return {}
    try:
        data = json.loads(COOKIES_FILE.read_text())
        return data.get("cookies", {})
    except Exception:
        return {}


def has_valid_session() -> bool:
    """True if we have at least the required Ancestry session cookie."""
    cookies = load_cookies()
    return all(k in cookies for k in _REQUIRED)


def session_age_hours() -> float | None:
    """How many hours since cookies were last saved, or None if not saved."""
    if not COOKIES_FILE.exists():
        return None
    try:
        data = json.loads(COOKIES_FILE.read_text())
        saved_at = data.get("saved_at", 0)
        return (time.time() - saved_at) / 3600
    except Exception:
        return None


def cookies_summary() -> str:
    cookies = load_cookies()
    age = session_age_hours()
    age_str = f"{age:.1f}h ago" if age is not None else "never"
    return f"{len(cookies)} cookies saved ({age_str}), valid={has_valid_session()}"
