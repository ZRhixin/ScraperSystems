"""
NC Courts Portal — Session Manager

The portal is protected by AWS WAF CAPTCHA. This script launches a real
browser, lets it auto-solve the challenge (or you solve it manually once),
then saves the aws-waf-token cookie so the scraper can reuse it for days.

The ASP.NET session (20-minute idle timeout) is renewed automatically on
each scraper call by making a warm-up GET to the home page — no browser
needed for that part.

Usage (run once to establish WAF token, or when it expires):
    python -m court.nc.session

Or call from code:
    from court.nc.session import get_waf_token, build_session
"""
import json
import os
import sys
import time
from pathlib import Path

from curl_cffi import requests as cffi_requests

_TOKEN_FILE = Path(__file__).parent / "session_cookies.json"
_PORTAL_URL = "https://portal-nc.tylertech.cloud/Portal/Home/Dashboard/29"
_TOKEN_MAX_AGE_HOURS = 48  # aws-waf-token is valid for days

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# WAF token file I/O
# ---------------------------------------------------------------------------

def load_waf_token() -> str | None:
    """Return the cached aws-waf-token if it's still within max age."""
    if not _TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(_TOKEN_FILE.read_text())
        saved_at = data.get("saved_at", 0)
        if time.time() - saved_at > _TOKEN_MAX_AGE_HOURS * 3600:
            return None
        for c in data.get("cookies", []):
            if c.get("name") == "aws-waf-token":
                return c["value"]
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def save_cookies(cookies: list[dict]) -> None:
    _TOKEN_FILE.write_text(json.dumps({
        "saved_at": time.time(),
        "cookies": cookies,
    }, indent=2))
    print(f"[NC Courts] Session saved to {_TOKEN_FILE}")


# ---------------------------------------------------------------------------
# Browser session establishment (one-time, needed only for WAF token)
# ---------------------------------------------------------------------------

def refresh_waf_token(headless: bool = False) -> str:
    """
    Launch a browser to obtain a fresh aws-waf-token.
    Returns the token string.
    """
    from playwright.sync_api import sync_playwright

    print("[NC Courts] Opening browser to solve AWS WAF challenge...")
    if not headless:
        print("  A window will open. Solve the CAPTCHA if prompted.")
        print("  It will close automatically once the portal loads.")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=headless)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        page.goto(_PORTAL_URL, timeout=60000)

        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                title = page.title()
            except Exception:
                time.sleep(1)
                continue
            if title and title != "Human Verification":
                print(f"[NC Courts] Challenge passed. Page: {title}")
                break
            time.sleep(1)
        else:
            browser.close()
            raise TimeoutError(
                "CAPTCHA was not solved within 90 seconds. "
                "Run: python -m court.nc.session"
            )

        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        time.sleep(1)

        raw_cookies = ctx.cookies()
        browser.close()

    cookies = [
        {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/")}
        for c in raw_cookies
    ]
    save_cookies(cookies)

    for c in cookies:
        if c["name"] == "aws-waf-token":
            return c["value"]
    raise RuntimeError("aws-waf-token not found in browser cookies after challenge")


# ---------------------------------------------------------------------------
# Session factory — called by search.py for every request
# ---------------------------------------------------------------------------

def build_session() -> cffi_requests.Session:
    """
    Build a requests Session with a valid aws-waf-token and a fresh
    ASP.NET_SessionId (obtained by hitting the home page).

    The aws-waf-token is cached for up to 48 hours.
    The ASP.NET session is renewed on every call via a lightweight GET.
    """
    token = load_waf_token()
    if not token:
        # Need to re-solve the WAF challenge
        token = refresh_waf_token(headless=False)

    s = cffi_requests.Session(impersonate="chrome124")
    s.headers["User-Agent"] = _UA
    s.cookies.set("aws-waf-token", token, domain=".tylertech.cloud")

    # Warm up: hit the home page to create/renew the ASP.NET session.
    # This is cheap (< 2s) and ensures the session is always fresh.
    resp = s.get(_PORTAL_URL, timeout=20)
    if "Human Verification" in resp.text:
        # WAF token expired — force re-solve
        if _TOKEN_FILE.exists():
            _TOKEN_FILE.unlink()
        token = refresh_waf_token(headless=False)
        s.cookies.set("aws-waf-token", token, domain=".tylertech.cloud")
        s.get(_PORTAL_URL, timeout=20)

    return s


# ---------------------------------------------------------------------------
# CLI — python -m court.nc.session
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    force = "--force" in sys.argv

    existing = load_waf_token()
    if existing and not force:
        print("[NC Courts] WAF token is still valid. Use --force to refresh anyway.")
        sys.exit(0)

    try:
        token = refresh_waf_token(headless=False)
        print(f"[NC Courts] WAF token saved. Valid for {_TOKEN_MAX_AGE_HOURS}h.")
    except Exception as e:
        print(f"[NC Courts] ERROR: {e}")
        sys.exit(1)
