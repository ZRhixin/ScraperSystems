# Business Understanding — Trusted Heir Solutions

## The Business

Trusted Heir Solutions is a real estate company that identifies and purchases fractional
ownership interests in heir property. Heir property occurs when a property owner dies
without formally transferring the property to their heirs. The heirs legally own shares
of the property but often do not know it, are not managing it, and are not paying taxes
on it. The company locates these properties, identifies the living heirs, and offers to
purchase their share.

---

## What We Are Looking For

- Properties where the owner of record is deceased
- Properties where ownership has never been formally transferred after death
- Properties with delinquent or unpaid taxes (strong signal of no active management)
- Fractional heir interests — who legally holds a share and has not yet sold it
- Living heirs with contact information who can be approached with an offer

---

## NC Intestate Succession (No Will)

| Surviving relatives | Distribution |
|---|---|
| Spouse + children | Spouse gets 1/3, children split 2/3 equally |
| Children only | Split equally among all children |
| No spouse or children | Parents first, then siblings |

If a child or heir is also deceased, their share passes to their own heirs. This is how
a single property can end up with 10-20 living claimants across multiple generations.
These sub-deceased owners need the same structured data capture as the primary owner:
date of death, marital status, will, estate.

---

## Research Process (Full Chain)

### Step 1 — Property Value Check
Determine if the property is worth pursuing. Pull assessed value, estimate ARV,
calculate net equity after taxes owed. Minimum threshold is $60,000 net value
(override possible with reason).

### Step 2 — Chain of Title Confirmation
Confirm how the current owner on record acquired the property. Four stages:

**Stage 1 — Assessor Lookup**
Search county assessor by parcel ID (fall back to address). Pull: owner name, legal
description, last transfer date, book/page of last deed. Check if assessor owner
matches owner on file. Flag mismatch but continue.

**Stage 2 — Find the Deed**
Three paths in order:
1. Assessor gave direct deed link → follow it, download
2. Assessor gave book/page but no link → go to Register of Deeds, look up by book/page
3. Assessor gave nothing → go to Register of Deeds, run grantee search on owner name,
   match legal description

**Stage 3 — Analyze the Deed**
Extract: deed type, grantor(s), grantee(s), vesting language, legal description,
recording date, book/page. Determine ownership form:
- One grantee = sole ownership
- Two grantees with married language = tenancy by the entirety (TBE)
- Two+ grantees with JTWROS = joint tenancy with right of survivorship
- Two+ grantees, no qualifying language = tenancy in common (TIC)
- Trust or LLC in name = trust or entity

**Stage 4 — Court Records (Probate)**
Triggered when no deed found OR deed type is Personal Representative / Trustee /
Deed of Distribution. Search NC Clerk of Superior Court, Estates Division. Pull:
estate file, final account, order of distribution, deed of distribution.

Final status options:
- confirmed_via_deed
- confirmed_via_inheritance_with_deed
- confirmed_via_inheritance_no_deed
- deed_referenced_unretrievable
- unconfirmed

**Foreclosure Check (runs after chain of title is confirmed)**
Check two sources for active tax foreclosure:

**Source 1 — County Tax Bill Portal**
Search by parcel ID. Extract bill flags from results:
- `TAXSALE` — parcel referred to foreclosure counsel
- `ATTORNEY` — attorney actively handling it
- `DLQ` — delinquent
- `ADVERTISED` — tax lien publicly advertised (pre-foreclosure step)

Each county has its own portal. Example (Cumberland):
`https://taxpwa.co.cumberland.nc.us/publicwebaccess/BillSearchResults.aspx?ParcelNum={PARCEL_ID}`

**Source 2 — NC Courts Portal (Tyler Tech / Odyssey)**
URL: https://portal-nc.tylertech.cloud — statewide, no public API, requires Playwright.
Run two searches per property:
- Party name search on the owner of record
- Party name search on each known heir

Cases that indicate tax foreclosure:
- Case type = CV (Civil Action)
- Plaintiff = a taxing unit (e.g. "County of Cumberland", "City of Fayetteville")

**The 5 Stages of a Tax Foreclosure**
| Stage | Triggering Event | Meaning |
|---|---|---|
| NO_CASE | No matching court case found | No foreclosure filed |
| PRE_JUDGMENT | Case filed, no Civil Judgment yet | Filed, court hasn't ruled |
| POST_JUDGMENT_PRE_SALE | Civil Judgment entered, no Report of Sale | Court ruled, sale not yet held |
| ACTIVE_UPSET_BIDDING | Report of Sale filed, no Order of Confirmation | Sale held, upset bid window open |
| SALE_CONFIRMED | Order of Confirmation entered | Sale is final |

**Key Case Events to Parse (Register of Actions)**
| Event Text | What It Means |
|---|---|
| Case filed, summons issued | Case just started |
| Granted in Whole or Part + Civil Judgment entered | Court ruled for the county |
| Report of Sale filed | Initial sale happened, upset bid window opens |
| Upset Bid Filed | Bidding in progress — includes last day to bid |
| Order of Confirmation entered | Sale is final |
| Motion to Default Bidder | Winning bidder didn't pay, sale may reset |
| Notice of Sale/Resale | New sale date scheduled |
| Alias Pluries Summons | Still trying to serve heirs |

**Real Example**
- Parcel: 0417-13-7284, Cumberland County
- Tax bills: TAXSALE + ATTORNEY + DLQ flags, 2021–2025. Total delinquent: $9,438.13
- Court case: 24CV011010-250, filed 11/21/2024
- Events: Civil Judgment 5/27/2025 → Report of Sale 6/26/2025 → ~30 Upset Bids
- Most recent bid: $88,200 by Sky REI LLC, last day to bid 4/27/2026
- Stage: ACTIVE_UPSET_BIDDING

If any stage other than NO_CASE is found → flag the property, pause research,
route to manual review before proceeding to heir identification.

### Step 3 — Skip Genie Lookup
Confirm owner is deceased. Build family tree to identify potential heirs.
Inputs: full name of deceased owner, last known address, death date if known.
Output: spouse, children, relatives, phone numbers, addresses.

### Step 4 — Obituary Search
Confirm deceased status independently. Find family names mentioned in obituary
that may identify heirs not found via SkipGenie.

### Step 5 — Heir Identification and Share Calculation
Apply NC intestate succession rules to calculate each heir's fractional share.
Account for sub-deceased heirs (their share passes to their own heirs).

### Step 6 — Cross-Check Heirs Against Deed Records
For each identified heir, search deed records as grantor. If they filed a deed
transferring their interest out, they no longer hold a share. Only heirs with
no outgoing deed are active targets.

### Step 7 — Contact Living Heirs
Use SkipGenie contact info and deed mailing addresses to reach out with purchase offer.

---

## Artifacts Rule
Every source document found (deed, estate file, court order, deed of distribution)
must be downloaded and uploaded to the property record in the database. If a document
cannot be downloaded, write the reference (book/page, instrument number, case number)
to the property record and mark it as unretrievable.

---

## Name Variation Logic
Apply when a name search returns nothing:
- Nicknames vs formal (Bob/Robert, Bill/William, Peggy/Margaret)
- Middle name: full, initial, or omitted
- Suffixes: with or without Jr., Sr., II, III
- Maiden vs married names
- Hyphenated last names with and without hyphen
- Entity formatting (LLC vs L.L.C.)
- Initials-only variants
- Fuzzy matching for misspellings

---

## Deed Name Suffixes
| Suffix | Meaning |
|---|---|
| /EST | Estate of (owner is deceased) |
| /EXTX | Executor of estate |
| /A IN F | Attorney in Fact |
| /SUCR A IN F | Successor Attorney in Fact |
| /TR | Trustee |

---

## The realestate Project (D:\Github\realestate)

The main application. A full-stack web app with:
- **Backend:** FastAPI (Python), PostgreSQL via SQLAlchemy
- **Frontend:** React/TypeScript
- **Key services:**

| Service | Purpose |
|---|---|
| `scraper_dispatcher.py` | Routes tax scrapes by county to the right scraper |
| `skipgenie_service.py` | SkipGenie integration (already built) |
| `court_research_service.py` | Court research (already built) |
| `research_queue_service.py` | Research pipeline queue |
| `research_automation_service.py` | Automated research workflow |
| `wizard_service.py` | Research wizard (7-step process) |
| `deceased_owner_manager.py` | Manages deceased owner records |

Tax scrapers already built for: Wake, Mecklenburg, New Hanover, Buncombe, Cumberland,
Chatham, Davidson, Orange, Beaufort, Carteret, Union, Pitt, Harris TX, Bexar TX,
Travis TX. Do not rebuild these.

**Research Wizard Steps:**
1. Property Value Check
2. Ownership Confirmation (chain of title) ← current focus
3. Skip Genie Lookup
4. (further steps not yet mapped)

---

## The scraperstesting Project (D:\Github\scraperstesting)

Scraper development environment. Builds new scrapers for assessor and deed lookups
(the realestate project only has tax scrapers). Exposes all scrapers via a single
HTTP server on port 8000.

### Server (server.py)
Single unified server, routes by path:
```
POST /county/wake/assessor     — Wake County assessor
POST /county/wake/deeds        — Wake County Register of Deeds
POST /county/mecklenburg/assessor
POST /county/newhanover/assessor
POST /county/buncombe/assessor
POST /skipgenie
GET  /                         — health check
```

### Folder Structure
```
scraperstesting/
├── county/
│   ├── wakecounty/
│   │   ├── assessor/    — search.py (owner, address, id, pin, account)
│   │   ├── deeds/       — search.py (Tyler Technologies Self-Service)
│   │   └── tax/
│   ├── mecklenburg/
│   │   └── assessor/    — search.py (Spatialest platform)
│   ├── newhanover/
│   │   └── assessor/    — search.py (iasWorld / Tyler Technologies)
│   └── buncombe/
│       └── assessor/    — search.py (Spatialest platform)
├── skipgenieapi/        — SkipGenie scraper
├── others/              — docs and reference files
└── server.py            — unified HTTP server (port 8000)
```

### Scraper Platforms
| Platform | Counties | Notes |
|---|---|---|
| Tyler Technologies Self-Service | Wake deeds | Java backend, JSESSIONID, two-step AJAX |
| Spatialest | Mecklenburg, Buncombe assessor | Laravel REST API, CSRF token |
| iasWorld (Tyler Technologies) | New Hanover assessor | ASP.NET WebForms, VIEWSTATE tokens |
| Wake County Assessor | Wake assessor | Custom platform |
| Blazor Server | Cumberland deeds | Needs Playwright, not built yet |

### Still To Build
- Wake County court records (NC Clerk of Superior Court) — needed for Stage 4 and
  foreclosure check
- New Hanover deeds
- Mecklenburg deeds
- Buncombe deeds
- Cumberland County (Playwright required)
- Obituary search scraper (Legacy.com / Dignity Memorial / local newspapers)

---

## n8n Setup

n8n runs locally on port 5680 (port 5678 is taken by Cursor IDE).
Start command:
```
set N8N_PORT=5680
set N8N_RUNNERS_BROKER_PORT=5682
n8n start
```

### Current Workflow — deed-verify (Step 2)

**Webhook:** POST `http://localhost:5680/webhook/deed-verify`

**Input:**
```json
{
  "property_address": "631 E NELSON AVE, Wake Forest, NC 27587",
  "county": "wake",
  "parcel_id": "0029590",
  "owner_name": "LYDIA HAYES",
  "is_deceased": null
}
```

**Flow:**
```
HeirMatrix (Webhook)
        ↓
AI Agent (Claude Sonnet 4.5)
  tools: Wake Assessor, Wake Deeds
        ↓
Code in JavaScript (strips markdown, parses JSON)
        ↓
Respond to HeirMatrix
```

**Output structure:**
```json
{
  "status": "confirmed_via_deed | confirmed_via_inheritance_with_deed | confirmed_via_inheritance_no_deed | deed_referenced_unretrievable | unconfirmed",
  "owner_mismatch": false,
  "ownership_form": "sole | tenancy_by_entirety | joint_tenancy | tenancy_in_common | trust | entity",
  "vesting_language": "",
  "co_owners": [],
  "grantor": "",
  "deed_type": "",
  "recording_date": "",
  "book_page": "",
  "legal_description": "",
  "is_deceased": null,
  "deceased_confidence": "confirmed | likely | unknown",
  "deceased_signals": [],
  "document_references": [],
  "flags": [],
  "summary": ""
}
```

### Tools Not Yet Wired (need scraper + n8n tool node)
- Mecklenburg Assessor + Deeds
- Buncombe Assessor + Deeds
- New Hanover Assessor + Deeds
- Court Records (Wake + other counties)

---

## Integration Plan

The scraperstesting server runs as a microservice. The realestate backend calls it via
HTTP when a researcher hits Step 2 of the research wizard. n8n sits between the two,
running the AI agent workflow:

```
realestate backend (wizard Step 2 triggered)
        ↓
POST http://localhost:5680/webhook/deed-verify
        ↓
n8n AI Agent (runs all stages, calls scraper tools)
        ↓
POST http://127.0.0.1:8000/county/wake/assessor
POST http://127.0.0.1:8000/county/wake/deeds
        ↓
Result JSON returned to realestate backend
        ↓
Backend writes result to property record in database
```
