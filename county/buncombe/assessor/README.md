# Buncombe County Assessor

**URL:** https://prc-buncombe.spatialest.com/
**Port:** 8005
**File:** `search.py`, `handler.py`

---

## Architecture

Same **Spatialest platform** as Mecklenburg County — modern Laravel REST API with a React/Vue single-page frontend. Clean JSON responses, no HTML parsing needed.

**Hosted by Spatialest** — the same third-party vendor. URL pattern `prc-buncombe.spatialest.com` is a dedicated subdomain for Buncombe rather than a path-based county prefix like Mecklenburg.

**No login required.** All data is publicly accessible.

**CSRF protection:** Same Laravel CSRF mechanism — token from `<meta name="csrf-token">` in the page HTML, sent as `X-Csrf-Token` header on every API call, tied to the `laravel_session` cookie.

---

## How We Use It

### Flow
```
GET  https://prc-buncombe.spatialest.com/
     → server sets XSRF-TOKEN and laravel_session cookies
     → HTML contains <meta name="csrf-token" content="...">

POST /api/v2/search/suggestions
     headers: X-Csrf-Token: <token>, X-Requested-With: XMLHttpRequest
     body (JSON): {"filters": {"term": "Maple"}, "debug": {...}}
     → JSON list of owner name suggestions with IDs

POST /api/v2/search
     headers: same
     body (JSON): {"filters": {"term": "Maple", "page": "1"}, "page": "1", "limit": 21, "debug": {...}}
     → JSON list of full property results
```

### Difference from Mecklenburg
The `/api/v2/search` payload includes `page` and `limit` parameters (Mecklenburg omits them). This enables pagination for broad searches.

---

## Search Inputs

| `search_type` | Required | Optional | Description |
|---|---|---|---|
| `search` | `term` | `page`, `limit` | Search by owner name, address, or parcel number |
| `suggestions` | `term` | — | Owner name autocomplete only |

**`page`** (int, default `1`): Page number for paginated results.

**`limit`** (int, default `21`): Results per page. The Burp capture showed `21` as the default; increase for broader searches.

The `term` field matches against:
- Owner name (partial match, e.g. `"Maple"` matches all owners with Maple)
- Street address (e.g. `"123 Merrimon Ave"`)
- Parcel number (e.g. `"9619-58-8888"`)

---

## Output

### `search` result
```json
{
  "parcel_id": "9619-58-8888",
  "internal_id": 123456,
  "address": "123 MERRIMON AVE ASHEVILLE NC",
  "owner": "SMITH JOHN A",
  "appraised_value": "$350,000",
  "latitude": "35.59012",
  "longitude": "-82.55123"
}
```

### `suggestions` result
```json
{
  "owner_id": "98765",
  "name": "MAPLE RIDGE LLC"
}
```

### Field notes
| Field | Notes |
|---|---|
| `parcel_id` | Buncombe County parcel number |
| `internal_id` | Spatialest platform internal ID — not a county identifier |
| `owner` | May contain multiple owners comma-separated |
| `appraised_value` | County appraised value as of last revaluation |
| `latitude` / `longitude` | Centroid coordinates of the parcel |

---

## Rate Limiting

Same Spatialest platform rate limit applies:
```
X-Ratelimit-Limit: 1000
X-Ratelimit-Remaining: 999
```

1000 requests per session. Each `search()` call creates a fresh session (new CSRF token + cookies), so the limit resets. Keep searches targeted.

---

## n8n Example Payloads

```json
{ "search_type": "search", "term": "Maple" }
{ "search_type": "search", "term": "123 Merrimon Ave" }
{ "search_type": "search", "term": "9619-58-8888" }
{ "search_type": "search", "term": "Maple", "page": 2, "limit": 50 }
{ "search_type": "suggestions", "term": "Maple" }
```

---

## Start Server
```
.venv\Scripts\python.exe -m buncombe.assessor.handler
```
