# Mecklenburg County Assessor

**URL:** https://property.spatialest.com/nc/mecklenburg/
**Port:** 8004
**File:** `search.py`, `handler.py`

---

## Architecture

Modern **Laravel REST API** (PHP framework) with a React/Vue single-page frontend. This is fundamentally different from the Wake County sites — responses are clean JSON, not HTML.

**Hosted by a third-party vendor** (Spatialest) that powers property search portals for multiple counties across the US. The URL pattern `/nc/mecklenburg/` indicates county-specific routing on a shared platform.

**No login required.** All data is publicly accessible.

**CSRF protection:** Laravel requires a CSRF token on all state-changing requests. The token is embedded as a `<meta name="csrf-token">` tag in the page HTML and must be sent as the `X-Csrf-Token` header on every API call. The token is tied to the `laravel_session` cookie.

---

## How We Use It

### Flow
```
GET  https://property.spatialest.com/nc/mecklenburg/
     → server sets XSRF-TOKEN and laravel_session cookies
     → HTML contains <meta name="csrf-token" content="...">

POST /nc/mecklenburg/api/v2/search/suggestions
     headers: X-Csrf-Token: <token>, X-Requested-With: XMLHttpRequest
     body (JSON): {"filters": {"term": "Bowes"}, "debug": {...}}
     → JSON list of owner name suggestions with IDs

POST /nc/mecklenburg/api/v2/search
     headers: same
     body (JSON): {"filters": {"term": "Bowes"}, "debug": {...}}
     → JSON list of full property results
```

### CSRF token extraction
```python
soup = BeautifulSoup(page_html, 'html.parser')
csrf = soup.find('meta', {'name': 'csrf-token'})['content']
```

### Why two endpoints?
- **`/suggestions`** — fast autocomplete. Matches owner names only. Returns owner ID + display name. Used by the website's search dropdown as you type.
- **`/search`** — full property search. Matches owner name, address, or parcel number. Returns complete property records.

### Discovery notes
The `suggestions` endpoint returns `id` values (e.g. `254720`) that represent owner IDs in the Spatialest database. These IDs were tested as filters on the `/search` endpoint but did not return targeted results — the search endpoint only accepts `term` as a filter. The owner IDs appear to be used for owner profile navigation within the frontend app and are not needed for standard property lookup.

---

## Search Inputs

| `search_type` | Required | Description |
|---|---|---|
| `search` | `term` | Search by owner name, address, or parcel number |
| `suggestions` | `term` | Owner name autocomplete only |

The `term` field matches against:
- Owner name (partial match, e.g. `"Bowes"` matches all Bowes owners)
- Street address (e.g. `"210 N Church"`)
- Parcel number (e.g. `"07848416"`)

---

## Output

### `search` result
```json
{
  "parcel_id": "07848416",
  "internal_id": 369815,
  "address": "210 N CHURCH ST CHARLOTTE NC",
  "owner": "MOORE JOSHUA C, BOWES JUSTINE R",
  "appraised_value": "$521,249",
  "latitude": "35.22921037741428",
  "longitude": "-80.84215799078953"
}
```

### `suggestions` result
```json
{
  "owner_id": "254720",
  "name": "BOWES DANIEL P"
}
```

### Field notes
| Field | Notes |
|---|---|
| `parcel_id` | Mecklenburg County parcel number (use for cross-referencing with deeds/tax) |
| `internal_id` | Spatialest platform internal ID — not a county identifier |
| `owner` | May contain multiple owners comma-separated |
| `appraised_value` | County appraised value as of last revaluation |
| `latitude` / `longitude` | Centroid coordinates of the parcel |

---

## Rate Limiting

The API response headers include:
```
X-Ratelimit-Limit: 1000
X-Ratelimit-Remaining: 999
```

1000 requests per session/IP. Exceeding this will result in `429 Too Many Requests`. Keep searches targeted — use specific names rather than single letters.

---

## n8n Example Payloads

```json
{ "search_type": "search", "term": "Bowes" }
{ "search_type": "search", "term": "210 N Church St" }
{ "search_type": "search", "term": "07848416" }
{ "search_type": "suggestions", "term": "Bowes" }
```

---

## Start Server
```
.venv\Scripts\python.exe -m mecklenburg.assessor.handler
```
