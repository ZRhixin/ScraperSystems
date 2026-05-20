"""
Playwright-based Ancestry.com login.

Handles ThreatMetrix device fingerprinting by running real Chromium JS.
Fires once per session (days/weeks between logins).

Usage:
    python -m ancestryapi.auto_login
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from . import session as sess

load_dotenv(Path(__file__).parent.parent / ".env")

_LOGIN_URL = "https://www.ancestry.com/account/signin"
_POST_LOGIN_PATH = "/account/signinframe"  # present during login, gone after


def login(headless: bool = False, timeout_ms: int = 60_000) -> bool:
    """
    Log into Ancestry using credentials from ANCESTRY_EMAIL / ANCESTRY_PASSWORD env vars.
    Saves cookies to ancestryapi/cookies.json.
    Returns True on success, False on failure.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("[!] playwright not installed. Run: pip install playwright && playwright install chromium")
        return False

    email = os.environ.get("ANCESTRY_EMAIL", "").strip()
    password = os.environ.get("ANCESTRY_PASSWORD", "").strip()
    if not email or not password:
        print("[!] ANCESTRY_EMAIL and ANCESTRY_PASSWORD must be set in .env")
        return False

    print(f"[*] Logging in as {email} (headless={headless})...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = ctx.new_page()

        try:
            page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)

            # Step 1: enter email and click Continue
            email_input = page.locator('input[type="email"], input[name="username"], input[id*="email"]').first
            email_input.wait_for(state="visible", timeout=timeout_ms)
            email_input.fill(email)

            continue_btn = page.locator('button[type="submit"], button:has-text("Continue")').first
            continue_btn.click()

            # Step 2: wait for password field (page may reload or reveal inline)
            try:
                password_input = page.locator('input[type="password"]').first
                password_input.wait_for(state="visible", timeout=timeout_ms)
            except PWTimeout:
                # Some flows show username+password on the same page
                password_input = page.locator('input[type="password"]').first
                password_input.wait_for(state="visible", timeout=10_000)

            password_input.fill(password)

            sign_in_btn = page.locator('button[type="submit"], button:has-text("Sign In"), button:has-text("Log In")').first
            sign_in_btn.click()

            # Step 3: wait for redirect away from signin page
            page.wait_for_url(
                lambda url: "/account/signin" not in url,
                timeout=timeout_ms,
            )

            # Small pause so Ancestry sets all session cookies
            time.sleep(2)

            # Step 4: extract cookies
            raw_cookies = ctx.cookies()
            cookies = {c["name"]: c["value"] for c in raw_cookies}

            # Validate we got the required cookies
            missing = [k for k in ("ANCSESSIONID", "ATT") if k not in cookies]
            if missing:
                print(f"[!] Login may have failed — missing cookies: {missing}")
                print(f"    Got: {list(cookies.keys())}")
                # Still save what we have — might be enough
                if cookies:
                    sess.save_cookies(cookies)
                return False

            sess.save_cookies(cookies)
            print(f"[+] Login successful. Session age: 0.0h, cookies: {len(cookies)}")
            return True

        except PWTimeout:
            print("[!] Login timed out. Page may require manual CAPTCHA or 2FA.")
            return False
        except Exception as exc:
            print(f"[!] Login error: {exc}")
            return False
        finally:
            browser.close()


def ensure_session(headless: bool = True) -> bool:
    """
    Returns True if a valid session exists.
    Triggers auto-login if session is missing or expired.
    """
    if sess.has_valid_session():
        age = sess.session_age_hours()
        print(f"[*] Session valid (age {age:.1f}h)")
        return True

    print("[*] No valid session — triggering auto-login...")
    return login(headless=headless)


if __name__ == "__main__":
    headless = "--visible" not in sys.argv
    success = login(headless=headless)
    sys.exit(0 if success else 1)
