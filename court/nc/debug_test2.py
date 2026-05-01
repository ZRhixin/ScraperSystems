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

# Get the SmartSearchResults page to find the portlet.smartSearchResults.js URL
r0 = s.get(f"{BASE}/Portal/Home/Dashboard/29", timeout=20)
js_urls = re.findall(r"(/Portal/Scripts/[^\s\"']+smartSearchResults[^\s\"']+)", r0.text)
print("JS URL:", js_urls[:2])

if js_urls:
    r = s.get(f"{BASE}{js_urls[0]}", timeout=20)
    code = r.text
    # Find LoadPartyData
    idx = code.find("LoadPartyData")
    if idx >= 0:
        print("\n=== LoadPartyData:")
        print(code[max(0, idx-300):idx+600])
    else:
        print("LoadPartyData not found")
        # Save the JS to inspect
        with open("court/nc/results_portlet.js", "w", encoding="utf-8") as f:
            f.write(code)
        print(f"Saved {len(code)} bytes to results_portlet.js")
