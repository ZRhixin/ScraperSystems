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
s.post(
    f"{BASE}/Portal/SmartSearch/SmartSearch/SmartSearch",
    data=payload,
    headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": f"{BASE}/Portal/Home/Dashboard/29"},
    allow_redirects=False,
    timeout=30,
)

ts = int(time.time() * 1000)
r2 = s.get(
    f"{BASE}/Portal/SmartSearch/SmartSearchResults",
    params={"_": ts},
    headers={"Referer": f"{BASE}/Portal/SmartSearch/SmartSearch"},
    timeout=60,
)
html = r2.text

# Save full HTML to inspect
with open("court/nc/results_sample.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Saved {len(html)} bytes to results_sample.html")

# Look for party-card or similar structures
for kw in ["party-card", "partyCard", "party-name", "data-party", "party-result", "smartSearchParty", "SmartSearch3rdTab"]:
    idx = html.find(kw)
    if idx >= 0:
        print(f"\n=== {kw} @ {idx}:")
        print(html[max(0, idx-50):idx+300])
