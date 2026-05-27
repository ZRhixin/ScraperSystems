"""
SkipGenie search API client.
Runs full browser simulation before every search so server logs are
indistinguishable from a real Chrome session.
"""
import os

from curl_cffi import requests

from . import session as sess
from .browser_sim import simulate_pre_search, _cookies, _UA, BASE_URL


def _get_proxy() -> dict | None:
    host = os.getenv("PROXY_HOST")
    port = os.getenv("PROXY_PORT")
    user = os.getenv("PROXY_USER")
    pwd  = os.getenv("PROXY_PASS")
    if not host or not port or not user or not pwd:
        return None
    return {"https": f"http://{user}:{pwd}@{host}:{port}",
            "http":  f"http://{user}:{pwd}@{host}:{port}"}

SEARCH_URL = f"{BASE_URL}/api/skipgenie/work_order_search"
_SEC_CH_UA = '"Not-A.Brand";v="24", "Chromium";v="146"'


def _search_headers(token: str) -> dict:
    return {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Authorization": token,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/user/search?tab=name",
        "Sec-Ch-Ua": _SEC_CH_UA,
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": _UA,
        "Priority": "u=1, i",
    }


def search_person(
    token: str,
    first_name: str = "",
    last_name: str = "",
    middle_name: str = "",
    street_address: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
) -> dict:
    session_data = sess.load() or {}
    user_id = session_data.get("user_id", "")

    http = requests.Session(impersonate="chrome120", proxies=_get_proxy())
    http.cookies.update(sess.load_cookies())

    # Fire pre-search background requests (credits refresh, search history)
    simulate_pre_search(http, token, user_id)

    optional = {k: v for k, v in {
        "firstName": first_name,
        "middleName": middle_name,
        "lastName": last_name,
        "address": street_address,
        "city": city,
        "state": state,
        "zip": zip_code,
    }.items() if v}

    payload = {**optional, "type": "2", "filter_blk_list": "true"}
    print(f"[*] Search payload: {payload}")

    try:
        resp = http.post(
            SEARCH_URL,
            data=payload,
            headers=_search_headers(token),
            cookies=_cookies(token),
            timeout=30,
            verify=False,
        )
        if resp.status_code in (401, 403):
            return {"error": "unauthorized"}
        resp.raise_for_status()
        body = resp.json()

        if body.get("status") != 1 or not body.get("data"):
            return {"status": "no_results", "raw": body}

        return _parse_result(body)

    except requests.RequestException as e:
        return {"error": str(e)}


def _parse_result(body: dict) -> dict:
    records = body["data"]
    results = []
    for i, record in enumerate(records):
        results.append({
            "result_index": i + 1,
            "subject_name": record.get("subjectName", ""),
            "age": record.get("age", ""),
            "dob": record.get("DOB", ""),
            "dod": record.get("DOD", ""),
            "deceased": record.get("deceased", "") == "DECEASED",
            "addresses": record.get("addressSearch", []),
            "phones": record.get("phones", []),
            "emails": record.get("emails", []),
            "possible_relatives": record.get("possibleRelatives", []),
            "possible_associates": record.get("possibleAssociates", []),
            "pid": record.get("pid", ""),
        })
    return {
        "result_count": len(results),
        "results": results,
        "search_id": body.get("search_id", ""),
        "credits_remaining": body.get("last_credit"),
    }
