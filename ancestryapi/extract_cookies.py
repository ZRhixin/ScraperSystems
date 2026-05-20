"""
Extract cookies and headers from a cURL command copied from Chrome DevTools.

Usage:
  1. Log into ancestry.com in Chrome
  2. DevTools → Network → perform a search on Ancestry
  3. Right-click any ancestry.com XHR/Fetch request → Copy → Copy as cURL (bash)
  4. Run:
       python -m ancestryapi.extract_cookies

  The script will prompt you to paste the curl command, then save
  the cookies to ancestryapi/cookies.json and print the request headers
  so you can fill in SEARCH_URL and SEARCH_HEADERS in search.py.
"""
import json
import re
import sys
from pathlib import Path

from . import session as sess


def parse_curl(curl_cmd: str) -> tuple[str, dict, dict]:
    """
    Parse a cURL command (bash format from Chrome DevTools).
    Returns (url, headers, cookies).
    """
    # Extract URL
    url_match = re.search(r"curl\s+'([^']+)'", curl_cmd)
    if not url_match:
        url_match = re.search(r'curl\s+"([^"]+)"', curl_cmd)
    url = url_match.group(1) if url_match else ""

    # Extract -H 'Header-Name: value' pairs
    headers = {}
    for m in re.finditer(r"-H\s+'([^:]+):\s*([^']*)'", curl_cmd):
        name, value = m.group(1).strip(), m.group(2).strip()
        headers[name] = value
    for m in re.finditer(r'-H\s+"([^:]+):\s*([^"]*)"', curl_cmd):
        name, value = m.group(1).strip(), m.group(2).strip()
        headers[name] = value

    # Split Cookie header into individual cookies
    cookies = {}
    cookie_header = headers.pop("Cookie", headers.pop("cookie", ""))
    if cookie_header:
        for part in cookie_header.split(";"):
            part = part.strip()
            if "=" in part:
                k, _, v = part.partition("=")
                cookies[k.strip()] = v.strip()

    return url, headers, cookies


def main():
    print("Paste the cURL command from Chrome DevTools (press Enter twice when done):")
    lines = []
    while True:
        try:
            line = input()
            if line == "" and lines and lines[-1] == "":
                break
            lines.append(line)
        except EOFError:
            break

    curl_cmd = "\n".join(lines)
    if not curl_cmd.strip():
        print("[!] No input provided. Exiting.")
        sys.exit(1)

    url, headers, cookies = parse_curl(curl_cmd)

    print(f"\n[+] URL:     {url}")
    print(f"[+] Cookies: {len(cookies)} found")
    for k in ("ANCSESSIONID", "cf_clearance", "ANCUUID", "ANC"):
        val = cookies.get(k, "(missing)")
        print(f"      {k}: {val[:40]}..." if len(val) > 40 else f"      {k}: {val}")

    print(f"\n[+] Headers ({len(headers)}):")
    for k, v in headers.items():
        print(f"      {k}: {v}")

    # Save cookies
    sess.save_cookies(cookies)

    # Print search.py snippet
    print("\n" + "="*60)
    print("Add this to ancestryapi/search.py:")
    print("="*60)
    print(f'SEARCH_URL = "{url}"')
    print("\nSEARCH_HEADERS = {")
    for k, v in headers.items():
        if k.lower() not in ("cookie", "content-length"):
            print(f'    "{k}": "{v}",')
    print("}")


if __name__ == "__main__":
    main()
