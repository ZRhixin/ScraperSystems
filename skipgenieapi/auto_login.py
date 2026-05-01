"""
Automated SkipGenie login — pure HTTP, no browser.
Uses 2captcha to solve reCAPTCHA v2, then POSTs credentials to the login API.
"""
import asyncio
import os
import time
import uuid

from curl_cffi import requests
from dotenv import load_dotenv
from twocaptcha import TwoCaptcha

from . import session as sess

load_dotenv()

EMAIL = os.getenv("SKIPGENIE_EMAIL")
PASSWORD = os.getenv("SKIPGENIE_PASSWORD")
API_KEY = os.getenv("TWOCAPTCHA_API_KEY")

LOGIN_URL = "https://web.skipgenie.com/api/auth/login"
RECAPTCHA_SITEKEY = "6LcLcC0qAAAAAEmq2GVhG6PXds23KHI0Ki0tB7jv"
RECAPTCHA_PAGE_URL = "https://web.skipgenie.com/"

_DEVICE_ID_FILE = sess.SESSION_FILE.parent / "device_id.txt"


def _get_device_id() -> str:
    if _DEVICE_ID_FILE.exists():
        return _DEVICE_ID_FILE.read_text().strip()
    device_id = str(uuid.uuid4())
    _DEVICE_ID_FILE.write_text(device_id)
    return device_id


def _solve_recaptcha() -> str:
    if not API_KEY:
        raise RuntimeError("TWOCAPTCHA_API_KEY not set in .env")
    print("[*] Sending reCAPTCHA to 2captcha...")
    solver = TwoCaptcha(API_KEY)
    result = solver.recaptcha(sitekey=RECAPTCHA_SITEKEY, url=RECAPTCHA_PAGE_URL)
    token = result["code"]
    print(f"[*] Got token: {token[:30]}...")
    return token


def login() -> str | None:
    """
    Solve reCAPTCHA and POST to login API.
    Returns the JWT token on success, None on failure.
    """
    recaptcha_token = _solve_recaptcha()
    device_id = _get_device_id()

    payload = {
        "email": EMAIL,
        "password": PASSWORD,
        "keep_me": "false",
        "url": "auth/login",
        "recaptcha": recaptcha_token,
        "device_id": device_id,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://web.skipgenie.com",
        "Referer": "https://web.skipgenie.com/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }

    # Use a persistent session — browser_sim reuses same TCP connection after login
    from .browser_sim import simulate_login_page, simulate_post_login
    http_session = requests.Session(impersonate="chrome120")

    # Step 1: Load the login page (as a real browser would before filling the form)
    simulate_login_page(http_session)

    print("[*] POSTing login credentials...")
    resp = http_session.post(LOGIN_URL, data=payload, headers=headers, timeout=30, verify=False)
    resp.raise_for_status()
    body = resp.json()

    if body.get("status") != 1:
        print(f"[!] Login failed: {body.get('message')}")
        return None

    token = body["data"]["token"]
    user_id = body["data"].get("id", "")
    plan_id = (body["data"].get("active_plan") or {}).get("plan_id", "")
    expires_at = time.time() + 86400
    sess.save(token, expires_at, user_id=user_id, plan_id=plan_id)
    sess.save_cookies(dict(http_session.cookies))
    print(f"[+] Login successful. Token saved (expires in 24h).")

    # Step 2: Simulate post-login dashboard loads
    simulate_post_login(http_session, token, user_id, plan_id)

    return token


if __name__ == "__main__":
    import urllib3
    urllib3.disable_warnings()
    t = login()
    print("[+] Done" if t else "[!] Login failed")
