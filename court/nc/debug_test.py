import re
import time
from court.nc.session import get_session_cookies
from curl_cffi import requests as cffi_requests

cookies = get_session_cookies()
s = cffi_requests.Session(impersonate="chrome124")
s.headers["User-Agent"] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
for c in cookies:
    s.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

BASE = "https://portal-nc.tylertech.cloud"

payload = {
    "Settings.CaptchaEnabled": "False",
    "caseCriteria.SearchCriteria": "HAYES, LYDIA",
    "caseCriteria.CourtLocation": "All Locations",
    "caseCriteria.SearchBy": "SmartSearch",
    "caseCriteria.SearchCases": "true",
    "caseCriteria.SearchByPartyName": "true",
    "Search": "Submit",
}
resp = s.post(
    f"{BASE}/Portal/SmartSearch/SmartSearch/SmartSearch",
    data=payload,
    headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": f"{BASE}/Portal/Home/Dashboard/29"},
    allow_redirects=False,
    timeout=30,
)
print("POST:", resp.status_code, "SmartSearchCriteria:", s.cookies.get("SmartSearchCriteria", "NONE"))

ts = int(time.time() * 1000)
r2 = s.get(
    f"{BASE}/Portal/SmartSearch/SmartSearchResults",
    params={"_": ts},
    headers={"Referer": f"{BASE}/Portal/SmartSearch/SmartSearch"},
    timeout=60,
)
html = r2.text
print("Results:", r2.status_code, "len:", len(html))

# Find all Portal URLs
all_portals = re.findall(r"/Portal/[A-Za-z/]+", html)
unique = sorted(set(all_portals))
print("Portal URLs found:", len(unique))
for u in unique[:30]:
    print(" ", u)

# Find data clues
for kw in ["PartyResult", "PartiesGrid", "Party/Grid", "PartyId", "CaseResults"]:
    idx = html.find(kw)
    if idx >= 0:
        print(f"\n=== {kw} @ {idx}:")
        print(html[max(0, idx-50):idx+200])
