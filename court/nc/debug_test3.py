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

# Submit search
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
print("SmartSearchCriteria:", s.cookies.get("SmartSearchCriteria", "NONE"))

# Get results page
ts = int(time.time() * 1000)
r2 = s.get(
    f"{BASE}/Portal/SmartSearch/SmartSearchResults",
    params={"_": ts},
    headers={"Referer": f"{BASE}/Portal/SmartSearch/SmartSearch"},
    timeout=60,
)
html = r2.text
print("Results status:", r2.status_code, "len:", len(html))

# Find the JS URL
js_urls = re.findall(r"(/Portal/Scripts/[^\s\"']+smartSearchResults[^\s\"']+)", html)
print("JS URLs:", js_urls[:3])

if js_urls:
    r = s.get(f"{BASE}{js_urls[0]}", timeout=20)
    code = r.text
    print("JS status:", r.status_code, "len:", len(code))

    # Save to disk and search
    with open("court/nc/results_portlet.js", "w", encoding="utf-8") as f:
        f.write(code)
    print("Saved JS")

    for kw in ["LoadPartyData", "partyData", "Party/Load", "partyGrid"]:
        idx = code.find(kw)
        if idx >= 0:
            print(f"\n=== {kw} @ {idx}:")
            print(code[max(0, idx-100):idx+400])
