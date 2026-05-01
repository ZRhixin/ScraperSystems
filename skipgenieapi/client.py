"""
SkipGenie API client entry point.
Checks session → auto-logins if expired → calls search API.
"""
from . import session as sess
from .auto_login import login
from .search import search_person


def get_token() -> str | None:
    token = sess.get_token()
    if token:
        return token
    print("[*] No valid session — logging in...")
    return login()


def lookup(
    first_name: str = "",
    last_name: str = "",
    middle_name: str = "",
    street_address: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
) -> dict:
    if not sess.check_and_increment():
        return {"error": "daily_cap_reached", "message": f"Daily search cap of {sess.DAILY_CAP} reached"}

    token = get_token()
    if not token:
        return {"error": "login_failed", "message": "Could not obtain a valid session token"}

    result = search_person(
        token=token,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        street_address=street_address,
        city=city,
        state=state,
        zip_code=zip_code,
    )

    # If API returns 401/403, session may be stale — retry once with fresh login
    if result.get("error") == "unauthorized":
        print("[*] Token rejected — re-logging in...")
        token = login()
        if not token:
            return {"error": "login_failed", "message": "Re-login failed"}
        result = search_person(
            token=token,
            first_name=first_name,
            last_name=last_name,
            middle_name=middle_name,
            street_address=street_address,
            city=city,
            state=state,
            zip_code=zip_code,
        )

    return result


if __name__ == "__main__":
    import json
    result = lookup(first_name="James", last_name="Smith", city="Miami", state="FL")
    print(json.dumps(result, indent=2))
