"""Test the search directly after session refresh."""
import re
import time
from court.nc.session import get_session_cookies
from curl_cffi import requests as cffi_requests

cookies = get_session_cookies()
s = cffi_requests.Session(impersonate="chrome124")
s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
    "caseCriteria.UseSoundex": "true",
    "Search": "Submit",
}
print("Posting...")
resp = s.post(f"{BASE}/Portal/SmartSearch/SmartSearch/SmartSearch",
              data=payload,
              headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": f"{BASE}/Portal/Home/Dashboard/29"},
              allow_redirects=False, timeout=30)
print("POST:", resp.status_code, s.cookies.get("SmartSearchCriteria", "NONE"))

time.sleep(2)  # brief wait

print("Getting results...")
ts = int(time.time() * 1000)
r2 = s.get(f"{BASE}/Portal/SmartSearch/SmartSearchResults",
           params={"_": ts},
           headers={"Referer": f"{BASE}/Portal/SmartSearch/SmartSearch"},
           timeout=120)
print("Results:", r2.status_code, "len:", len(r2.text))

import json
match = re.search(r'"data"\s*:\s*\{\s*"Data"\s*:\s*(\[)', r2.text)
if match:
    start = match.start(1)
    depth = 0; in_str = False; escape = False
    for i in range(start, len(r2.text)):
        ch = r2.text[i]
        if escape: escape = False; continue
        if ch == "\\" and in_str: escape = True; continue
        if ch == '"': in_str = not in_str; continue
        if in_str: continue
        if ch == '[': depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                raw = r2.text[start:i+1]
                break
    parties = json.loads(raw)
    print(f"Parsed {len(parties)} parties")
    for p in parties[:3]:
        print(f"  {p.get('NameFirst','')} {p.get('NameLast','')} - {p.get('CaseResultCount',0)} cases")
