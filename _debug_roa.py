"""
Test /Portal/DocumentViewer/DisplayDoc with curl_cffi using saved portal cookies.
Then load the Embedded viewer and extract the PDF.
"""
import json, base64
from pathlib import Path
from urllib.parse import quote
from curl_cffi import requests as cffi_requests

BASE  = "https://portal-nc.tylertech.cloud"
UA    = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# From CaseEvents data
CASE_NUM     = "24E002839-910"
LOCATION_ID  = "101092003"
CASE_ID      = "55423494"   # internal integer CaseId from CaseEvents response

# Documents: (FragmentID, docTypeId?, docType, docName, eventName)
# docTypeId=12 is what the user's browser sent — try with that
DOCS = [
    ("30850458", "12", "Other",   "Other/Miscellaneous",                    "Other/Miscellaneous"),
    ("30780885", "12", "Other",   "Receipt (Partial or Final)",             "Receipt (Partial or Final)"),
    ("30681048", "12", "Other",   "Paid Funeral Bill",                      "Paid Funeral Bill"),
    ("30681392", "12", "Other",   "Other/Miscellaneous",                    "Other/Miscellaneous"),
    ("30680648", "12", "Other",   "Application for Administration by Clerk","Application for Administration by Clerk"),
    ("30632212", "12", "Other",   "Proof of Death",                         "Proof of Death"),
    ("31964651", "12", "Other",   "Payments to Clerk (NCGS 28A-25-6)",      "Payments to Clerk (NCGS 28A-25-6)"),
]

saved = json.loads(Path("court/nc/session_cookies.json").read_text())
s = cffi_requests.Session(impersonate="chrome124")
s.headers.update({
    "User-Agent": UA,
    "Referer":    f"{BASE}/app/RegisterOfActions/",
    "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
})
for c in saved.get("cookies", []):
    s.cookies.set(c["name"], c["value"], domain=c.get("domain", ".tylertech.cloud"))

for frag_id, doc_type_id, doc_type, doc_name, event_name in DOCS:
    url = (
        f"{BASE}/Portal/DocumentViewer/DisplayDoc"
        f"?documentID={frag_id}"
        f"&caseNum={quote(CASE_NUM)}"
        f"&locationId={LOCATION_ID}"
        f"&caseId={CASE_ID}"
        f"&docTypeId={doc_type_id}"
        f"&isVersionId=false"
        f"&docType={quote(doc_type)}"
        f"&docName={quote(doc_name)}"
        f"&eventName={quote(event_name)}"
    )
    print(f"\n--- {doc_name} (FragmentID={frag_id}) ---")
    r = s.get(url, allow_redirects=False, timeout=20)
    print(f"  DisplayDoc → {r.status_code}")

    if r.status_code in (301, 302, 303, 307):
        location = r.headers.get("location", "")
        print(f"  Redirect → {location[:80]}")

        # Follow the redirect
        if not location.startswith("http"):
            location = BASE + location
        r2 = s.get(location, timeout=20, allow_redirects=True)
        print(f"  Embedded → {r2.status_code}  ct={r2.headers.get('content-type','')[:40]}")
        if b"%PDF" in r2.content[:8]:
            print(f"  *** PDF DIRECT ({len(r2.content):,} bytes) ***")
            Path(f"_test_doc_{frag_id}.pdf").write_bytes(r2.content)
        else:
            # Show first 500 chars of HTML for embedded viewer
            html = r2.text[:600]
            print(f"  HTML preview: {repr(html[:300])}")

    elif r.status_code == 200:
        ct = r.headers.get("content-type", "")
        if b"%PDF" in r.content[:8]:
            print(f"  *** PDF ({len(r.content):,} bytes) ***")
            Path(f"_test_doc_{frag_id}.pdf").write_bytes(r.content)
        else:
            print(f"  200 ct={ct}  preview={repr(r.text[:200])}")
    elif r.status_code == 202:
        print(f"  WAF block (202)")
    else:
        print(f"  {r.status_code}: {r.text[:200]}")
