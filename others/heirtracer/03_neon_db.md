# Neon PostgreSQL DB — ScraperSystems

**Connection string:** (in `ScraperSystems/.env`)  
`postgresql://neondb_owner:npg_hE64TNdnvyla@ep-blue-sky-amk4p6qm.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require`

This is the **ScraperSystems** Neon DB — used exclusively by the chain of ownership workflow and scrapers. It is NOT the FPILS/realestate DB.

## Existing Tables (as of 2026-05-11)

| Table | Purpose |
|-------|---------|
| `_migrations` | Schema migration tracking |
| `appraiser_transfer_history` | County assessor transfer data |
| `chain_conclusions` | **Chain of ownership final output — heir tracer reads this** |
| `court_captures` | NC court/probate search results |
| `document_extractions` | Extracted deed/document data |
| `heir_traces` | **Heir tracer final output** (already created) |
| `incidental_records` | Misc findings during investigation |
| `investigation_questions` | Agent Q&A during investigation |
| `investigation_sessions` | Investigation session tracking |
| `investigation_trace` | Step-by-step trace log |
| `properties` | Property records (NC heir property leads) |
| `rod_captures` | Register of Deeds deed records |

## heir_traces Schema (already exists)

```sql
CREATE TABLE heir_traces (
  id SERIAL PRIMARY KEY,
  property_id INTEGER NOT NULL,
  conclusion_id INTEGER NOT NULL REFERENCES chain_conclusions(id),
  root_decedent_name TEXT NOT NULL,
  heir_tree JSONB NOT NULL,          -- Full heir tree with shares
  living_heir_count INTEGER,
  total_credits_used INTEGER,
  status TEXT DEFAULT 'draft',       -- draft | complete | manual_review | partial
  gaps JSONB,
  fpils_synced_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

## chain_conclusions Key Columns

```sql
-- Key fields the heir tracer queries:
id, property_id, session_id, verdict, status, stop_reason,
current_owners JSONB,  -- array with estate_path_unresolved, approx_death_year, etc.
created_at
```

## What Still Needs to Be Added

The `estate_analyst_runs` table referenced in the Estate Analyst spec belongs in the **FPILS/realestate DB**, NOT here. These Neon tables are purely for the scraper/chain-of-ownership pipeline.

## Tables NOT Here (in FPILS/realestate DB instead)

- `properties` (different schema from Neon properties)
- `property_people` — all persons (owners, heirs, relatives)
- `property_people_relationships` — family relationships
- `research_events` — step-based task queue for agents
- `research_documents` — evidence files
- `property_cases` — probate/estate court cases
- `facts` — FPILS fact records (DOD, marital status, will, etc.)
- `estate_computations` — FPILS share calculations
- `interest_ledger_entries` — per-person share ledger
- `estate_analyst_runs` — **needs to be created in FPILS DB**
