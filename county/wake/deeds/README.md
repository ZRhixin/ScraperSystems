# Wake County Register of Deeds

**URL:** https://rodrecords.wake.gov/
**Port:** 8007
**File:** `search.py`, `handler.py`

---

## Architecture

**Tyler Technologies Self-Service** — Java backend (JSESSIONID session cookie). Clean two-step AJAX flow: POST to validate the search and get page count, then GET to retrieve HTML results per page.

**No login required.** All data is publicly accessible.

**Disclaimer cookie:** Set `disclaimerAccepted=true` directly — no need to navigate the disclaimer page.

---

## How We Use It

### Flow
```
GET  /web/search/DOCSEARCH341S2
     cookies: disclaimerAccepted=true
     → server sets JSESSIONID cookie

POST /web/searchPost/DOCSEARCH341S2
     headers: Ajaxrequest: true, X-Requested-With: XMLHttpRequest
     body (form): field_GranteeID_DOT_Surname=Bowes&...
     → JSON: {"validationMessages":{},"totalPages":3,"currentPage":1}

GET  /web/searchResults/DOCSEARCH341S2?page=1&_=<timestamp>
     headers: Ajaxrequest: true, X-Requested-With: XMLHttpRequest
     → HTML results page with deed rows

GET  /web/document/DOCC554325?search=DOCSEARCH341S2   (optional detail)
     → HTML detail page with full deed fields
```

---

## Search Inputs

| `search_type` | Required | Optional |
|---|---|---|
| `name` | `surname` | `first_name`, `role`, `start_date`, `end_date`, `doc_types`, `page`, `fetch_details` |
| `document` | `document_number` | `fetch_details` |
| `detail` | `doc_id` | — |

### Field notes

**`role`** — who to search as:
- `"both"` (default) — appears as either grantor or grantee
- `"grantor"` — person who transferred/sold the property
- `"grantee"` — person who received the property

**`doc_types`** — filter by document type (array):
```json
["DEED", "QUIT CLAIM DEED", "AFFIDAVIT"]
```

All types observed: AFFIDAVIT, ASSUMED NAME, DEED, MEMORANDUM, MORTGAGE, PARTIAL RELEASE, POWER OF ATTORNEY, QUIT CLAIM DEED, RELEASE, SATISFACTION, SEE INSTRUMENT

**`start_date` / `end_date`** — format `MM/DD/YYYY`

**`page`** — page number (default 1). Pass `0` to fetch all pages.

**`fetch_details`** — if `true`, fetches the full detail page for each result. Adds one HTTP request per deed.

---

## Output

### Name/document search result (list only)
```json
{
  "doc_id": "DOCC554325",
  "doc_type": "DEED",
  "recording_date": "05/31/1990",
  "grantor": "WILLIAMS & WILLIAMS HOMES OF EXCELLE",
  "grantee": "BOWES ELIZABETH H",
  "document_number": "004714-00624"
}
```

### Full detail result (`fetch_details: true` or `search_type: detail`)
```json
{
  "doc_id": "DOCC554325",
  "document_number": "004714-00624",
  "recording_date": "05/31/1990",
  "doc_type": "DEED",
  "num_pages": "2",
  "book": "004714",
  "page": "00624",
  "grantor": "WILLIAMS & WILLIAMS HOMES OF EXCELLE",
  "grantee": ["BOWES ELIZABETH H", "BOWES TIMOTHY E"],
  "legal": "LT 28 PHASE 2 SOUTH MEADOWS"
}
```

### Name suffix codes (appear in grantor/grantee names)
| Suffix | Meaning |
|---|---|
| `/EST` | Estate of (owner is deceased) |
| `/EXTX` | Executor of estate |
| `/A IN F` | Attorney in Fact |
| `/SUCR A IN F` | Successor Attorney in Fact |
| `/TR` | Trustee |

These suffixes are critical for heir research — `/EST` confirms a deceased owner, `/EXTX` identifies who managed the estate.

---

## Heir Research Use

For a given deceased owner:
1. Search by surname as **grantor** — find all deeds where they transferred property out
2. Search by surname as **grantee** — find all deeds where they received property
3. Filter to `doc_types: ["DEED", "QUIT CLAIM DEED", "AFFIDAVIT"]`
4. Look for `/EST` or `/EXTX` suffixes — confirms estate transfer occurred
5. For each heir identified via SkipGenie, search their name to check if they already transferred their share

---

## n8n Example Payloads

```json
{ "search_type": "name", "surname": "Bowes" }
{ "search_type": "name", "surname": "Bowes", "role": "grantee", "fetch_details": true }
{ "search_type": "name", "surname": "Smith", "first_name": "John", "role": "grantor" }
{ "search_type": "name", "surname": "Bowes", "doc_types": ["DEED", "QUIT CLAIM DEED"] }
{ "search_type": "name", "surname": "Bowes", "start_date": "01/01/2000", "end_date": "12/31/2020" }
{ "search_type": "document", "document_number": "004714-00624", "fetch_details": true }
{ "search_type": "detail", "doc_id": "DOCC554325" }
```

---

## Start Server
```
.venv\Scripts\python.exe -m wakecounty.deeds.handler
```
