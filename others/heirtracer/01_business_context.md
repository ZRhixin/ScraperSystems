# Business Context — TitleMatrix / Trusted Heir Solutions

## What the Company Does

TitleMatrix (operating as Trusted Heir Solutions) is a North Carolina real estate company that buys **fractional ownership interests in heir property**. When a property owner dies without formally transferring ownership, the property passes by NC intestate succession law to their heirs — but the heirs often don't know they own anything and the property sits with delinquent taxes and no active management. TitleMatrix locates those heirs, calculates their shares, and makes purchase offers.

## The 7-Step Research Pipeline

| Step | Task | Status |
|------|------|--------|
| 1 | Property Value Check (≥$60K net after taxes) | Manual |
| 2 | Chain of Title — confirm owner is deceased, property is unresolved heir property | **DONE (n8n)** |
| 3 | SkipGenie Lookup — confirm deceased, get relatives/contact info | Building |
| 4 | Obituary Search — confirm death independently, find survivors | Building |
| 5 | Heir Identification + Share Calculation (NC Ch. 29) | Building |
| 6 | Cross-check heirs against deed records | Future |
| 7 | Contact living heirs, make offers | Manual |

**Current focus:** Steps 3–5 are being automated via an n8n multi-agent workflow (the "heir tracer").

## Infrastructure

| Component | Port/Location | Purpose |
|-----------|---------------|---------|
| n8n | localhost:5680 | Workflow engine (5678 taken by Cursor) |
| ScraperSystems server | localhost:8000 | HTTP server: county scrapers, SkipGenie, write endpoints |
| SkipGenie API | localhost:8001 | Existing working API |
| SSDI scraper | localhost:8003 | Planned (FamilySearch) |
| Neon PostgreSQL | cloud (scraperstesting DB) | Chain of ownership workflow DB |
| Realestate DB | localhost:5432/property_database | FPILS CRM DB |

## Two Codebases

- `C:\Users\Summer Ishi\Github\TitleMatrix\ScraperSystems` — Scraper/n8n dev environment. Port 8000 server. Contains all n8n workflow JSON files.
- `C:\Users\Summer Ishi\Github\TitleMatrix\realestate` — Main FastAPI/React CRM (FPILS system). Manages property_people, facts, heir deals, family tree, computations.

## NC Intestate Succession (Chapter 29) — Quick Reference

Chapter 29 applies when: NC domicile + no valid will + property not distributed by devise.

**Distribution order (GS 29-15):**
1. Children/descendants (if none → step 2)
2. Parents (if none → step 3)
3. Siblings/their descendants (if none → step 4)
4. Grandparents, aunts/uncles (if none → step 5)
5. Collateral kin to 5 degrees only — beyond 5 degrees = **escheat**

**Spouse share (GS 29-14):**
- Spouse + 1 child: spouse gets 1/2 real property
- Spouse + 2+ children: spouse gets 1/3 real property
- Spouse + parents (no children): spouse gets 1/2
- Spouse alone: spouse gets all

**Dollar threshold (personal property floor) — GS 29-14(b):**
- Deaths before 2012: $30K (with children) / $50K (with parents)
- Deaths 2012+: $60K (with children) / $100K (with parents)

**Cascade rule:** If an heir is also deceased, run Chapter 29 again for that heir. Continue recursively until all branches end at living people, escheat, or human review.

**Special rules:** Half-blood = full blood (GS 29-3). Adopted inherits from adoptive family only. Out-of-wedlock: always from mother; from father only if paternity established per specific NC statutes.

**Pre-1960 deaths:** Chapter 29 effective Jan 1, 1960. Deaths before that → prior common law applies → escalate to human review.
