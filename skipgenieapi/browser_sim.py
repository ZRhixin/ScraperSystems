"""
Simulates the full HTTP request sequence a real Chrome browser makes on SkipGenie.
Based on Burp Suite capture of a real login-to-search session.

Full sequence replicated (skipgenie.com calls only — google.com reCAPTCHA
calls are on a different domain and handled by 2captcha):

  GET  /                                         login page load
  POST /api/auth/login                           login (auto_login.py)
  GET  /user/search?_rsc={id}                    RSC page fetch after redirect
  POST /api/plan/get_plans                       (x3 — React re-renders)
  GET  /api/user/getPersonalizedCreditRateForAPI (x6 — polling)
  GET  /api/user/credit_setting                  (x6 — polling)
  POST /api/notification/get_user_notifications
  POST /api/user/search_history                  (x2)
  GET  /api/user/get_my_credits                  (x20 — active polling loop)
  POST /api/skipgenie/work_order_search          actual search (search.py)
"""
import os
import random
import string
import time

from curl_cffi import requests

BASE_URL = "https://web.skipgenie.com"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)
_SEC_CH_UA = '"Not-A.Brand";v="24", "Chromium";v="146"'

EMAIL = os.getenv("SKIPGENIE_EMAIL", "")
PASSWORD = os.getenv("SKIPGENIE_PASSWORD", "")


def _rsc_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=5))


def _cookies(token: str) -> dict:
    return {"email": EMAIL, "pass": PASSWORD, "utoken": token}


def _nav_headers(referer: str = "") -> dict:
    h = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": _SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": _UA,
    }
    if referer:
        h["Referer"] = referer
        h["Sec-Fetch-Site"] = "same-origin"
    return h


def _rsc_headers(referer: str) -> dict:
    return {
        "Accept": "text/x-component",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Next-Router-State-Tree": "%5B%22%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%5D%7D%2Cnull%2Cnull%2Ctrue%5D",
        "Next-Url": "/user/search",
        "Rsc": "1",
        "Sec-Ch-Ua": _SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Referer": referer,
        "User-Agent": _UA,
    }


def _xhr_post_headers(token: str, referer: str) -> dict:
    return {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": token,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": BASE_URL,
        "Referer": referer,
        "Sec-Ch-Ua": _SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": _UA,
        "Priority": "u=1, i",
    }


def _xhr_get_headers(token: str, referer: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": token,
        "Origin": BASE_URL,
        "Referer": referer,
        "Sec-Ch-Ua": _SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": _UA,
        "Priority": "u=1, i",
    }


def _get(session: requests.Session, url: str, headers: dict, cookies: dict) -> None:
    path = url.replace(BASE_URL, "")
    try:
        resp = session.get(url, headers=headers, cookies=cookies, timeout=10, verify=False)
        print(f"  GET  {path} -> {resp.status_code}")
    except Exception as e:
        print(f"  GET  {path} -> ERROR: {e}")


def _post(session: requests.Session, url: str, data: dict, headers: dict, cookies: dict) -> None:
    path = url.replace(BASE_URL, "")
    try:
        resp = session.post(url, data=data, headers=headers, cookies=cookies, timeout=10, verify=False)
        print(f"  POST {path} -> {resp.status_code}")
    except Exception as e:
        print(f"  POST {path} -> ERROR: {e}")


def _pause(min_s: float, max_s: float) -> None:
    time.sleep(random.uniform(min_s, max_s))


def simulate_login_page(session: requests.Session) -> None:
    """Step 1: GET the login page as Chrome does before filling credentials."""
    print("[sim] Loading login page...")
    cookies = {"email": EMAIL, "pass": PASSWORD}
    _get(session, f"{BASE_URL}/", _nav_headers(), cookies)
    _pause(1.5, 3.0)


def simulate_post_login(
    session: requests.Session,
    token: str,
    user_id: str,
    plan_id: str,
) -> None:
    """
    After login succeeds, replicate every background request Chrome fires.
    Matches the exact sequence captured in Burp Suite.
    """
    cookies = _cookies(token)
    referer_login = f"{BASE_URL}/"
    referer_search = f"{BASE_URL}/user/search"
    post_h = _xhr_post_headers(token, referer_search)
    get_h = _xhr_get_headers(token, referer_search)

    print("[sim] Post-login: navigating to search page...")
    _get(session, referer_search, _nav_headers(referer=referer_login), cookies)
    _pause(0.3, 0.7)

    print("[sim] RSC fetch...")
    _get(session, f"{BASE_URL}/user/search?_rsc={_rsc_id()}", _rsc_headers(referer_login), cookies)
    _pause(0.1, 0.3)

    # Wave 1 — React components mount and fire initial fetches
    _post(session, f"{BASE_URL}/api/plan/get_plans",
          {"plan_type": "2", "active_plan_id": plan_id, "privacy": "1"}, post_h, cookies)
    _pause(0.05, 0.15)

    _get(session, f"{BASE_URL}/api/user/getPersonalizedCreditRateForAPI", get_h, cookies)
    _pause(0.05, 0.15)

    _get(session, f"{BASE_URL}/api/user/credit_setting", get_h, cookies)
    _pause(0.05, 0.15)

    # Wave 2 — React re-renders trigger second round
    _post(session, f"{BASE_URL}/api/plan/get_plans",
          {"plan_type": "2", "active_plan_id": plan_id, "privacy": "1"}, post_h, cookies)
    _pause(0.05, 0.15)

    _post(session, f"{BASE_URL}/api/notification/get_user_notifications",
          {"uid": user_id}, post_h, cookies)
    _pause(0.05, 0.15)

    _post(session, f"{BASE_URL}/api/user/search_history",
          {"start": "0", "limit": "5", "user_id": user_id, "type": "3"}, post_h, cookies)
    _pause(0.05, 0.15)

    # Wave 3 — third re-render cycle
    _post(session, f"{BASE_URL}/api/plan/get_plans",
          {"plan_type": "2", "active_plan_id": plan_id, "privacy": "1"}, post_h, cookies)
    _pause(0.1, 0.2)

    _get(session, f"{BASE_URL}/api/user/credit_setting", get_h, cookies)
    _pause(0.05, 0.1)

    _get(session, f"{BASE_URL}/api/user/getPersonalizedCreditRateForAPI", get_h, cookies)
    _pause(0.05, 0.1)

    _get(session, f"{BASE_URL}/api/user/credit_setting", get_h, cookies)
    _pause(0.05, 0.1)

    _get(session, f"{BASE_URL}/api/user/getPersonalizedCreditRateForAPI", get_h, cookies)
    _pause(0.05, 0.1)

    _get(session, f"{BASE_URL}/api/user/getPersonalizedCreditRateForAPI", get_h, cookies)
    _pause(0.05, 0.1)

    _get(session, f"{BASE_URL}/api/user/credit_setting", get_h, cookies)
    _pause(0.05, 0.1)

    _post(session, f"{BASE_URL}/api/user/search_history",
          {"start": "0", "limit": "5", "user_id": user_id, "type": "3"}, post_h, cookies)
    _pause(0.1, 0.2)

    # Credit polling loop — React polls get_my_credits every ~3s while user is on page
    # Real session showed 20 calls; we simulate 8-14 (user spends ~30-50s on page)
    poll_count = random.randint(8, 14)
    print(f"[sim] Credit polling loop ({poll_count} calls, ~{poll_count*3}s)...")
    for i in range(poll_count):
        _get(session, f"{BASE_URL}/api/user/get_my_credits", get_h, cookies)
        _pause(2.5, 4.0)
    print("[sim] Post-login simulation complete.")


def simulate_pre_search(
    session: requests.Session,
    token: str,
    user_id: str,
) -> None:
    """
    Just before submitting — a few more credit polls fire while the user
    fills out the form, then a short pause simulating hovering over submit.
    """
    cookies = _cookies(token)
    referer = f"{BASE_URL}/user/search?tab=name"
    get_h = _xhr_get_headers(token, referer)
    post_h = _xhr_post_headers(token, referer)

    # A few more polls while user types into the form
    for _ in range(random.randint(2, 4)):
        _get(session, f"{BASE_URL}/api/user/get_my_credits", get_h, cookies)
        _pause(2.5, 4.0)

    _get(session, f"{BASE_URL}/api/user/credit_setting", get_h, cookies)
    _pause(0.1, 0.3)

    _post(session, f"{BASE_URL}/api/user/search_history",
          {"start": "0", "limit": "5", "user_id": user_id, "type": "3"},
          post_h, cookies)

    # Simulate user pausing before clicking submit
    _pause(0.8, 2.0)
