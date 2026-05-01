# Wake County Assessor (Real Estate)

**URL:** https://services.wake.gov/realestate/
**Port:** 8002
**File:** `search.py`, `handler.py`

---

## Architecture

Classic **ASP (Active Server Pages)** site — circa early 2000s. No JSON API. All responses are HTML pages parsed with BeautifulSoup.

**No login required.** All data is publicly accessible.

**Session requirement:** The server requires an `ASPSESSIONID` cookie which is issued on the first `GET` request. Without it, search requests are rejected. We always `GET` the search page first before any POST.

---

## How We Use It

### Flow
```
GET  /realestate/Search.asp
     → server sets ASPSESSIONID cookie

POST /realestate/DoSearchByOwner.asp    (or ByAddr, ByID, ByPin)
     → 302 redirect to results page

GET  /realestate/OwnerList.asp          (or ValidateAddress, PinList)
     → HTML table of results (parsed with BeautifulSoup)

GET  /realestate/Account.asp?id=XXXXXXX
     → HTML detail page (parsed with regex on plain text)
```

### Why regex for detail page?
The detail page (`Account.asp`) is a deeply nested ASP classic table with no consistent CSS classes or IDs. Extracting labeled values using `get_text(separator='|')` and then matching `Label | Value` patterns with regex was more reliable than trying to navigate the table structure.

**Edge case handled:** Some fields (e.g. `Heated Area`, `Total Value`) are empty on commercial/condo properties. When a field is empty, BeautifulSoup strips the empty cell and the next label gets matched as the value. Fixed by maintaining a set of known label names and rejecting any matched value that is itself a label.

---

## Search Inputs

| `search_type` | Required | Optional |
|---|---|---|
| `owner` | `last_name` | `first_name`, `fetch_details` |
| `address` | `street_name` | `street_number`, `fetch_details` |
| `id` | `real_estate_id` | `fetch_details` |
| `pin` | `map` | `sheet`, `block`, `lot`, `fetch_details` |
| `account` | `account_id` | — |

**`fetch_details`** (bool, default `false`): When `true`, each list result automatically fetches the full `Account.asp` detail page. Adds one HTTP request per result.

---

## Output

### List result (all search types except `account`)
```json
{
  "account_id": "0103838",
  "owner": "SMITH, JOHN",
  "location_address": "6101 VALLEYFIELD CIR",
  "city": "RALEIGH",
  "property_description": "LO104 VALLEY EST PT PHII BLDBM"
}
```

> Address results also include `owner` but have empty `city` and `property_description` — use `fetch_details: true` or follow up with an `account` search to get those.

### Full account detail (`account` search or `fetch_details: true`)
```json
{
  "account_id": "0103838",
  "pin": "0796596549",
  "owner": "SMITH, JOHN & ELLA ANN",
  "mailing_address": "6101 VALLEYFIELD CIR",
  "location_address": "6101 VALLEYFIELD CIR",
  "zoning": "R-4",
  "land_class": "R-<10-HS",
  "city": "RALEIGH",
  "township": "HOUSE CREEK",
  "acreage": ".36",
  "heated_area_sqft": "1,816",
  "deed_date": "12/1/1992",
  "deed_book_page": "05423 0649",
  "sale_date": "12/1/1992",
  "sale_price": "$116,500",
  "land_value": "$220,000",
  "building_value": "$254,961",
  "total_value": "$474,961",
  "permit_date": "9/12/2001",
  "permit_number": "0000013656"
}
```

### Optional fields (empty on some property types)
| Field | Empty when |
|---|---|
| `heated_area_sqft` | Land-only parcels, some condos |
| `sale_date` / `sale_price` | No recorded arms-length sale |
| `land_value` / `building_value` / `total_value` | Master condo records (value deferred to unit records) |
| `city` / `property_description` | Address and PIN list results (only in account detail) |

---

## n8n Example Payloads

```json
{ "search_type": "owner", "last_name": "Smith", "first_name": "John" }
{ "search_type": "owner", "last_name": "Smith", "first_name": "John", "fetch_details": true }
{ "search_type": "address", "street_name": "Valleyfield", "street_number": "6101" }
{ "search_type": "id", "real_estate_id": "0103838", "fetch_details": true }
{ "search_type": "pin", "map": "0796" }
{ "search_type": "account", "account_id": "0103838" }
```

---

## Start Server
```
.venv\Scripts\python.exe -m wakecounty.assessor.handler
```
