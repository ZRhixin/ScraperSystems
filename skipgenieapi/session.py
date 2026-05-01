"""
Session management — stores JWT token, user_id, plan_id, expiry, cookies, and daily search count.
Token lifetime is 24 hours per SkipGenie's JWT (exp - iat = 86400s).
"""
import datetime
import json
import os
import time
from pathlib import Path

SESSION_FILE = Path(__file__).parent / "session.json"
COOKIES_FILE = Path(__file__).parent / "cookies.json"
COUNTER_FILE = Path(__file__).parent / "daily_count.json"
BUFFER_SECONDS = 300  # refresh 5 min before actual expiry

DAILY_CAP = int(os.getenv("DAILY_SEARCH_CAP", "200"))


def save(token: str, expires_at: float, user_id: str = "", plan_id: str = "") -> None:
    SESSION_FILE.write_text(json.dumps({
        "token": token,
        "expires_at": expires_at,
        "user_id": user_id,
        "plan_id": plan_id,
    }))


def load() -> dict | None:
    if not SESSION_FILE.exists():
        return None
    data = json.loads(SESSION_FILE.read_text())
    if time.time() >= data["expires_at"] - BUFFER_SECONDS:
        return None
    return data


def get_token() -> str | None:
    data = load()
    return data["token"] if data else None


def save_cookies(cookies: dict) -> None:
    COOKIES_FILE.write_text(json.dumps(cookies))


def load_cookies() -> dict:
    if not COOKIES_FILE.exists():
        return {}
    try:
        return json.loads(COOKIES_FILE.read_text())
    except Exception:
        return {}


def check_and_increment() -> bool:
    """Returns True if the search is allowed, False if the daily cap is reached."""
    today = datetime.date.today().isoformat()
    data = {"date": today, "count": 0}
    if COUNTER_FILE.exists():
        try:
            saved = json.loads(COUNTER_FILE.read_text())
            if saved.get("date") == today:
                data = saved
        except Exception:
            pass
    if data["count"] >= DAILY_CAP:
        return False
    data["count"] += 1
    COUNTER_FILE.write_text(json.dumps(data))
    return True


def daily_count() -> int:
    today = datetime.date.today().isoformat()
    if not COUNTER_FILE.exists():
        return 0
    try:
        saved = json.loads(COUNTER_FILE.read_text())
        return saved.get("count", 0) if saved.get("date") == today else 0
    except Exception:
        return 0
