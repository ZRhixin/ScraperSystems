# Wake County Property Tax

**URL:** https://services.wake.gov/ptax/main/billing/
**Port:** 8003
**File:** `search.py`, `handler.py`

---

## Architecture

**ASP.NET WebForms** — Microsoft's server-side framework. Visually looks like a traditional HTML form site, but under the hood it uses a security mechanism called ViewState.

**No login required.** All data is publicly accessible.

**Key difference from Classic ASP:** Every page load generates two hidden tokens — `__VIEWSTATE` and `__EVENTVALIDATION` — that must be included in every POST. These tokens change on every session and cannot be hardcoded. Without them the server either rejects the request or throws a generic error.

---

## How We Use It

### Flow
```
GET  /ptax/main/billing/default.aspx
     → server sets ASP.NET_SessionId cookie
     → HTML contains __VIEWSTATE, __EVENTVALIDATION hidden fields

POST /ptax/main/billing/default.aspx?search=owner&yrs=10&last=X&first=Y&middle=Z&cnt=0
     body: __VIEWSTATE=...&__EVENTVALIDATION=...&ddlSearchBy=owner&txtLast=X&txtFirst=Y...
     → 302 redirect to NameBrowse.aspx

GET  /ptax/main/billing/NameBrowse.aspx?search=owner&yrs=10&last=X&first=Y&middle=
     → HTML table of results (parsed with BeautifulSoup)
```

### Token extraction
```python
soup = BeautifulSoup(page_html, 'html.parser')
viewstate = soup.find('input', {'name': '__VIEWSTATE'})['value']
eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})['value']
```

### Pagination
Results are paginated (50 per page). A "No Paging" button fires a JavaScript postback (`__doPostBack('ctlNameBrowse','noPage-')`) which loads all results at once. Use `all_pages: true` to trigger this.

---

## Search Inputs

| `search_type` | Required | Optional |
|---|---|---|
| `owner` | `last_name` | `first_name`, `middle_name`, `years`, `all_pages` |

**`years`** (int, default `10`): How many years of tax history to return. Options observed: 2, 5, 10, or all.

**`all_pages`** (bool, default `false`): Fetches all pages at once using the "No Paging" postback. Use with caution on broad searches (e.g. "Smith" returns 988+ records).

### Search types not yet working
`account` and `business` search types are present on the website but the server rejects submissions with a "Please enter a valid account number" error. The internal account number format expected by the search UI is different from the 10-digit account numbers returned in results. Needs further investigation.

---

## Output

### Result row
```json
{
  "name": "SMITH , JOHN JR",
  "account_number": "0511691681",
  "year": "2011",
  "type": "DMV",
  "description": "1993 PLYM 4S",
  "amount_due": "$0.00"
}
```

### Record types
| `type` | Meaning |
|---|---|
| `REI` | Real estate (property tax bill) |
| `DMV` | Motor vehicle (registered with NCDMV) |
| `BUS` | Business personal property |
| `IND` | Individual personal property |

### Notes
- One property can produce multiple rows — one per tax year
- `amount_due: "$0.00"` means the bill was paid, not that tax is zero
- DMV records may appear even if the vehicle is no longer owned

---

## n8n Example Payloads

```json
{ "search_type": "owner", "last_name": "Smith", "first_name": "John" }
{ "search_type": "owner", "last_name": "Bowes", "first_name": "E", "years": 10, "all_pages": true }
```

---

## Start Server
```
.venv\Scripts\python.exe -m wakecounty.tax.handler
```
