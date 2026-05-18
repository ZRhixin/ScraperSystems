# Heir Tracer — Context Memory

This directory is the permanent context foundation for designing and building the n8n heir tracer workflow. Load all files before any architecture discussion.

## Files

| File | Contents |
|------|---------|
| `01_business_context.md` | TitleMatrix business model, 7-step pipeline, infrastructure ports, NC Ch. 29 quick reference |
| `02_chain_of_ownership_workflow.md` | Chain of ownership n8n workflow — what it does, trigger condition, output schema, DB tables written |
| `03_neon_db.md` | ScraperSystems Neon DB — existing tables, heir_traces schema, what's NOT here |
| `04_fpils_crm.md` | Realestate CRM FPILS — property_people, research_events, facts, computations, key API endpoints |
| `05_estate_analyst_spec.md` | Estate Analyst agent spec — cascade loop, step taxonomy, DB schema (estate_analyst_runs), output format, human review triggers |
| `06_nc_chapter29.md` | Full NC Chapter 29 intestate succession law reference — all rules, statutes, special cases |

## Architecture Decision Points (to resolve before building)

1. **Two DBs:** ScraperSystems Neon (chain of ownership) vs FPILS DB (realestate). The heir tracer bootstrap reads from Neon, then writes to FPILS. Need FPILS DB connection string for n8n.

2. **estate_analyst_runs DDL:** Must be added to FPILS DB as a migration. DDL is in `05_estate_analyst_spec.md`.

3. **n8n auth for FPILS API:** Heir tracer n8n workflow needs a system user JWT to call realestate API endpoints. Need to create automation user and store JWT as n8n credential.

4. **Port conflict:** Realestate backend defaults to port 8000, same as ScraperSystems server. Must confirm actual ports in production.

5. **research_events polling interval:** n8n Schedule trigger (12–30s) polling for pending research_events with step in (10,20,30,40,99).

## What the Heir Tracer Must Do

1. **Bootstrap:** Poll Neon `chain_conclusions` for estate_path_unresolved = true with no existing FPILS person. Create root decedent in `property_people`. Insert step=10 + step=20 `research_events`.

2. **Skip Tracer (step 10):** Call port 8001 SkipGenie API. Write DOB, possible_relatives, addresses to `property_people.research_metadata`. Insert step=99.

3. **Obituary Search (step 20):** Web search for obituary. Write obituary_link, obituary_text, date_of_death to `property_people`. Insert step=99.

4. **SSDI Lookup (step 30):** FamilySearch API on port 8003 (to build). Write date_of_death, place_of_death. Insert step=99.

5. **Court Search (step 40):** Call port 8000 `/investigate/court-search`. Write to `property_cases` + `research_metadata.testacy`. Insert step=99.

6. **Estate Analyst (step 99):** LLM agent reads `v_estate_analyst_state`, applies Ch. 29, writes `estate_analyst_runs` row, dispatches new research_events for heirs/gaps.

7. **Cascade:** When Estate Analyst identifies a deceased heir, bootstrap that heir (steps 10+20). Continue until all branches resolved.

8. **Heir Tree Compiler:** Once root decedent's latest run = 'complete' and all cascades resolved, compile final output → write `heir_traces` row in Neon + trigger FPILS recompute.
