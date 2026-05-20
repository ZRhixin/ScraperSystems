"""
Ancestry.com scraper — curl_cffi + saved cookies.

Quick start:
  1. Log into ancestry.com in Chrome
  2. Open DevTools → Network → search for any person
  3. Right-click a search request → Copy → Copy as cURL
  4. Run:  python -m ancestryapi.extract_cookies  "<paste curl command>"
     This auto-populates ancestryapi/cookies.json
  5. Test: python -m ancestryapi.client
"""
