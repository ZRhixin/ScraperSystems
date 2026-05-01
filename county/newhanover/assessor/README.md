# New Hanover County Assessor

**URL:** https://etax.nhcgov.com/pt/
**Port:** 8006
**File:** `search.py`, `handler.py`

---

## Architecture

**iasWorld Public Access** by Tyler Technologies — a widely-used ASP.NET WebForms platform for county assessor data across the US. Returns HTML pages parsed with BeautifulSoup. No JSON API.

**No login required.** All data is publicly accessible.

**DISCLAIMER cookie required:** The site shows a disclaimer page on first visit. Instead of navigating through it, we set `DISCLAIMER=1` directly on the session before any request.

**ASP.NET tokens:** Same `__VIEWSTATE` and `__EVENTVALIDATION` mechanism as other ASP.NET sites — must be extracted from the page HTML before every POST. Tokens change each session.

---

## How We Use It

### Flow
```
GET  /pt/search/CommonSearch.aspx?mode=ADDRESS   (or OWNER or PARID)
     cookies: DISCLAIMER=1
     → server sets ASP.NET_SessionId cookie
     → HTML contains __VIEWSTATE, __EVENTVALIDATION hidden fields

POST /pt/search/CommonSearch.aspx?mode=ADDRESS
     body: __VIEWSTATE=...&__EVENTVALIDATION=...&inpStreet=Asheville&...
     → HTML results page with <tr class='SearchResults'> rows
```

### Token extraction
```python
soup = BeautifulSoup(page_html, 'html.parser')
viewstate = soup.find('input', {'name': '__VIEWSTATE'})['value']
eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})['value']
```

### Search modes
The mode is set both in the URL query string (`?mode=ADDRESS`) and as a hidden form field (`mode=ADDRESS`). Both must match.

---

## Search Inputs

| `search_type` | Required | Optional | Description |
|---|---|---|---|
| `address` | `street_name` | `street_number`, `suffix`, `direction`, `page`, `page_size` | Search by street name |
| `owner` | `owner_name` | `page`, `page_size` | Search by owner name |
| `parcel` | `parcel_id` | `page`, `page_size` | Search by parcel ID |

### Address field notes
- `street_name` — partial match (e.g. `"Asheville"` returns all Asheville streets)
- `suffix` — street type: `AVE`, `DR`, `ST`, `RD`, etc. Default `***` matches all
- `direction` — post-directional: `E`, `N`, `NE`, `S`, `SE`, `W`. Leave empty for all

### Pagination
- `page` (int, default 1) — page number
- `page_size` (int, default 25) — results per page. Site supports 10, 15, 20, 25

---

## Output

### Result row
```json
{
  "parcel_id": "R05720-031-010-000",
  "owner": "TERZAIN ANDREW M NNENNE M",
  "address": "1 ASHEVILLE ST E",
  "roll": "RP",
  "luc": "17"
}
```

### Roll types
| `roll` | Meaning |
|---|---|
| `RP` | Real Property |
| `PP` | Personal Property |
| `BP` | Business Personal Property |

### LUC (Land Use Code)
Numeric code assigned by the county assessor. Common values vary by county — look up in the county's LUC table for descriptions (e.g. 17 = single-family residential in New Hanover).

### Address normalization
The raw HTML splits the address across multiple lines (number, street name, direction on separate lines). We normalize by collapsing all whitespace to a single space.

---

## Known Limitations

- **Owner search confirmed** — field name `inpOwner` verified by Burp capture.
- **Parcel search confirmed** — field name `inpParid` verified by Burp capture.
- **Detail page not implemented** — each result row links to `/pt/Datalets/Datalet.aspx?sIndex=N&idx=N` for full property detail. Not yet implemented.

---

## n8n Example Payloads

```json
{ "search_type": "address", "street_name": "Asheville" }
{ "search_type": "address", "street_name": "Asheville", "street_number": "1", "direction": "E" }
{ "search_type": "address", "street_name": "Market", "suffix": "ST", "page": 2 }
{ "search_type": "owner", "owner_name": "Smith" }
{ "search_type": "parcel", "parcel_id": "R05720-031-010-000" }
```

---

## Start Server
```
.venv\Scripts\python.exe -m newhanover.assessor.handler
```
