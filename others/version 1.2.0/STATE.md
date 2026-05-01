# HeirMatrix Scraper System — State of Version 1.2.0

**Date:** 2026-04-30
**Working directory:** `D:\Github\scraperstesting`

---

## What the Client Wants: Overview

Given a parcel ID, produce a structured conclusion about:
- Who the current owner is
- How they acquired the property (deed, inheritance with distribution deed, court-only inheritance)
- How they hold title (vesting type — sole, tenancy by entirety, JTWROS, tenants in common, trust, entity)
- The supporting documents with citations
- Flags on anything unresolved

**Four layers in order: Scout → Investigate → Conclude → Verify**

Each layer reads from and writes to a database. Pass only IDs between n8n nodes — never full payloads.

**Two databases:**
- **Scraper DB** — owns the investigation: raw captures, sessions, trace, chain conclusions
- **Production FPILS** — receives only the final vesting conclusion as a seed fact (future handoff, not part of this build)

---

## Current n8n Workflow (v1.2.0) — What Exists Now

**Two separate workflows:**

### Workflow 1 — Scout (`POST /webhook/scout`)

```
HeirMatrix (Webhook POST /scout)
    → AI Agent (GPT-4o-mini)
        ↳ [tool] Wake Assessor   → POST /county/wake/assessor
    → Code in JavaScript (strip markdown, parse JSON)
    → HTTP Request → POST /scout/write  (writes to DB)
    → Respond to Webhook
```

**Input:** `{ "body": "<parcel_id>" }` or `{ "body": { ... } }`
**Output:** Structured property JSON written to `properties` + `appraiser_transfer_history` via `/scout/write`

### Workflow 2 — Investigator (`POST /webhook/investigate`)

```
HeirMatrix1 (Webhook POST /investigate)
    → AI Agent1 (GPT-4o-mini)
        ↳ [tool] Load Property State      → POST /investigate/property-state
        ↳ [tool] Pull Deed                → POST /investigate/pull-deed
        ↳ [tool] Read Document            → POST /investigate/read-document
        ↳ [tool] Wake Deeds               → POST /county/wake/deeds
        ↳ [tool] Court Search             → POST /court/nc/search
        ↳ [tool] Register of Actions      → POST /court/nc/register_of_actions
        ↳ [tool] Court Pull               → POST /investigate/court-pull
        ↳ [tool] Update Appraiser Verification → POST /investigate/update-appraiser-verification
        ↳ [tool] Log Incidental           → POST /investigate/log-incidental
        ↳ [tool] Open Question            → POST /investigate/open-question
        ↳ [tool] Resolve Question         → POST /investigate/resolve-question
        ↳ [tool] Settle Chain             → POST /investigate/settle-chain
        ↳ [tool] Flag Review              → POST /investigate/flag-review
        ↳ [tool] Buncombe Deeds           → POST /county/buncombe/deeds (stub)
        ↳ [tool] Mecklenburg Deeds        → POST /county/mecklenburg/deeds (stub)
    → Code in JavaScript1 (strip markdown, parse JSON)
```

**Input:** `{ "property_id": 1 }`
**Output:** Writes to rod_captures, document_extractions, investigation_sessions, chain_conclusions

### LLM nodes present (both workflows)

| Node | Model | Connected |
|------|-------|-----------|
| GPT (Scout) | gpt-4o-mini | ✅ Active |
| GPT1 (Investigator) | gpt-4o-mini | ✅ Active |
| Claude / Claude1 | claude-opus-4-6 | ❌ Disconnected |
| Moonshot Kimi Chat Model | kimi-k2.6 | ❌ Disconnected |

**Note on Kimi:** Attempted migration to Moonshot Kimi (kimi-k2.6) to avoid Anthropic Tier 1 TPM limits. Kimi's reasoning models break n8n multi-turn tool calling (`reasoning_content` missing error). Non-reasoning models (`moonshot-v1-128k`) don't trigger tools. Reverted to GPT-4o-mini. Revisit when Kimi's n8n integration matures.

### Known issue — `$fromAI("body")` with GPT-4o-mini

GPT-4o-mini returns tool arguments as a JavaScript object, not a JSON string. All `jsonBody` fields that use `$fromAI("body")` must be wrapped:
```
={{ JSON.stringify($fromAI("body")) }}
```
GPT-5 was not affected because it returned arguments as a string. All tool nodes in the Investigator workflow have been updated with `JSON.stringify`.

### Wake ROD software update (2026-04-xx)

Wake County updated their ROD platform to version 2026.1.2. The old PDF download URL (`/web/document/servepdf/SCALED-{doc_id}.1.pdf/...`) now returns HTTP 200 with 0 bytes. Fixed in `county/wake/deeds/search.py` — new URL pattern:
```
/web/document-image-pdf/{doc_id}//{image_name}-{index}.pdf?index={index}
```
Discovered by reading the updated JS file and `data-href` attribute in the pdfjs viewer HTML.

---

## Target Architecture — 4-Layer n8n Pipeline

The current workflow needs to be replaced with four separate n8n nodes:

```
Scout node
  → reads: parcel_id, state, county
  → runs: county adapter (fetchAppraiserData)
  → writes: properties row + appraiser_transfer_history rows
  → signals: complete (passes property_id)

Investigate node
  → reads: property_id (Scout must be complete)
  → runs: AI agent loop with tools (Phases A → B → C → D → E)
  → writes: rod_captures, court_captures, document_extractions,
            investigation_sessions, investigation_trace,
            investigation_questions, incidental_records
  → signals: settled or flagged_for_review (passes property_id)

Conclude node
  → reads: property_id + all document_extractions
  → runs: Conclude AI prompt (temp 0)
  → writes: chain_conclusions row (status=active, verify_status=pending)
  → signals: complete (passes chain_conclusion_id)

Verify node
  → reads: chain_conclusion_id + referenced document_extractions
           (does NOT read investigation_trace)
  → runs: Verify AI prompt (temp 0, different model instance)
  → writes: updates chain_conclusions.verify_status

Loopback:
  Verify returns objection_raised
    → route back to Investigate with objection context
    → new conclusion supersedes old
    → max ONE loopback per property; second objection → flagged_for_human
```

---

## The 5 AI Prompts (from `chain of title ai prompt.md`)

All prompts: strict JSON output only — no markdown, no code fences, no prose. Every claim must cite capture_id or extraction_id.

### Prompt 1 — Scout Appraiser Extraction
- **When:** After county adapter fetches raw appraiser content for a parcel
- **Input:** Raw text/HTML from appraiser site for one parcel
- **Output:** Structured JSON → writes to `properties` + `appraiser_transfer_history`
- **Temperature:** 0
- **Key rules:** Preserve owner names exactly as shown. `short_legal_parsed` only populated if subdivision/block/lot can be identified with high confidence. Never invent data — use null + extraction_note.

### Prompt 2 — Document Processing (document-read subroutine)
- **When:** After OCR produces text for any `rod_captures` or `court_captures` row
- **Input:** `ocr_text`, `ocr_confidence`, `parcel_reference` (short_legal_raw, subdivision, block, lot, plat_book, plat_page)
- **Output:** Structured JSON → writes to `document_extractions`
- **Temperature:** 0.2
- **Key rules:**
  - If `ocr_confidence < 0.75` → set `extraction_confidence = "low"` + flag `low_input_ocr_confidence`
  - `vesting_language` = verbatim language about how grantees hold title (exact phrase, not interpreted)
  - `references_prior_deed_book/page/language` = if deed cites a prior deed ("being the same property conveyed to grantor by deed at Book X Page Y"), capture it — critical for chain-back
  - `legal_match_to_parcel`: high (plat+lot all match), medium (subdivision+lot match), low (similar but ambiguous), none (clearly different)
  - `conveys_multiple_parcels` = true when deed covers multiple parcels
- **Flags to raise:** `low_ocr_readability`, `low_input_ocr_confidence`, `handwritten_document`, `cursive_or_old_formatting`, `multi_parcel_conveyance`, `corrective_or_quitclaim_deed`, `legal_description_mismatch`, `references_unretrieved_prior_deed`, `missing_critical_field`, `ambiguous_vesting_language`

### Prompt 3 — Investigate Agent System Prompt
- **When:** Investigate node runs; this is the agent's brain
- **Temperature:** 0.2
- **Type:** Agent loop — runs until it calls `settle_chain()` or `flag_for_review()`
- **Tools the agent calls** (these must exist as server endpoints or n8n tool nodes):

| Tool | What it does |
|------|-------------|
| `get_property_state(property_id)` | Returns Scout data, appraiser_transfer_history, existing extractions |
| `rod_search(name, role, date_range?)` | Searches ROD; role = "grantor" or "grantee" |
| `rod_pull(book, page)` | Pulls deed image → creates rod_captures row → returns capture_id |
| `court_search(name, date_range?)` | Searches NC Clerk of Superior Court |
| `court_pull(case_number, document_type)` | Pulls court document → creates court_captures row → returns capture_id |
| `read_document(capture_id)` | Runs OCR + Prompt 2 extraction → creates document_extractions row → returns extraction |
| `update_appraiser_verification(row_id, status, notes)` | Updates appraiser_transfer_history.verification_status |
| `log_incidental(extraction_id, record_type, summary)` | Adds to incidental_records |
| `open_question(text)` | Adds to investigation_questions → returns question_id |
| `resolve_question(question_id, resolution, notes)` | Closes a question |
| `log_trace(step_number, action, input, output)` | Appends to investigation_trace (call after every substantive action) |
| `settle_chain(primary_extraction_id, chain_back_extraction_id, summary)` | Marks investigation settled — terminal |
| `flag_for_review(reason, context)` | Marks investigation flagged — stops investigation — terminal |

- **Phases:**
  - **Phase A** — Verify each `appraiser_transfer_history` row: `rod_pull` at claimed book/page → `read_document` → compare → `update_appraiser_verification`
  - **Phase B** — Independent ROD search: search current owner as grantee + grantor; flag corrective/quitclaim/confirmation deeds
  - **Phase C** — Chain-back one hop: find acquisition deed → take its grantor → `rod_search(grantor, role="grantee", before primary date)` → verify grantor received this property. Try name variants (budget: 5). If primary cites a prior deed, pull it. If corrective deed appeared, investigate what it corrects.
  - **Phase D** — Estate path (only if no acquisition deed OR chain terminates in deceased owner): `court_search` → `court_pull` → `read_document` estate file/order of distribution/deed of distribution
  - **Phase E** — Incidentals throughout B-D: any non-chain document (mortgages, deeds of trust, releases, lis pendens, judgment liens, affidavits of death) → `read_document` → `log_incidental`

- **Name variant budget:** 5 attempts per name, in order: middle initial, nickname swap, first/last transposition, surname spelling variants, corporate suffix variants

- **Stopping conditions (call `flag_for_review` with reason string):**
  - `chain_unresolved_at_max_depth` — walked 3 hops without resolution
  - `name_variants_exhausted` — full variant budget spent, no match
  - `ocr_below_threshold_on_critical_document` — central document has `extraction_confidence = "low"`
  - `estate_path_unresolved` — Phase D found nothing
  - `legal_description_mismatch_unresolvable` — central document doesn't match parcel
  - `time_budget_exceeded` — 10 minutes elapsed

### Prompt 4 — Conclude
- **When:** After Investigate calls `settle_chain()` (or partial conclusion after `flag_for_review`)
- **Input:** `property_id` + `scout_data` + `investigation_session` outcome + all `extractions` + `investigation_flags`
- **Output:** JSON → writes to `chain_conclusions` with `status=active`, `verify_status=pending`
- **Temperature:** 0
- **Key outputs:**
  - `current_owners` array with normalized name, `is_deceased`, `deceased_confidence`, `deceased_signals` each citing `extraction_id`
  - `acquisition_type`: deed | inheritance_with_deed_of_distribution | inheritance_court_only | unresolved
  - `acquisition_document_refs`: primary doc, chain-back doc, supporting docs
  - `vesting` per NC rules (sole / tenancy_by_entirety / jtwros / tenants_in_common / trust / entity / unresolved)
  - `vesting_evidence`: `extraction_id` + `exact_language` verbatim from that extraction
  - `legal_description_confidence`: high (all chain extractions = high), medium (some medium, none low/none), low (any low/none)
- **Supersession rule:** If a `chain_conclusion` already exists for this property, mark old row `status=superseded`, populate `superseded_by_id`. Never overwrite.

### Prompt 5 — Verify
- **When:** After Conclude writes a `chain_conclusions` row with `verify_status=pending`
- **Input:** `chain_conclusions` row + every referenced `document_extractions`. **NOT** `investigation_trace`
- **Output:** JSON → updates `chain_conclusions.verify_status` + `verify_objections`
- **Temperature:** 0
- **Different model instance / fresh context from Conclude** — adversarial separation is intentional
- **7 checks it runs:**
  1. **Citation completeness** — are all `extraction_id` references populated and valid?
  2. **Acquisition match** — does the primary document's `grantee_names` include the current owner? Is `legal_match_to_parcel` high/medium?
  3. **Chain integrity** — does `chain_back_document` exist? Does its grantee match primary's grantor? Is its legal match high/medium?
  4. **Vesting support** — does `vesting_evidence.exact_language` actually support the claimed vesting type?
  5. **Deceased claims** — do the cited `extraction_id`s actually contain the claimed deceased signals?
  6. **Legal description confidence coherence** — does the claimed confidence match what the extractions actually justify?
  7. **Flag coherence** — if extractions have flags like `legal_description_mismatch`, does the conclusion carry corresponding flags?
- **Verdicts:** `approved` | `objection_raised` (resolvable, return to Investigate) | `flagged_for_human` (fundamental issue, human queue)

---

## Database Schema — What Needs to Be Built

All new tables go in the Scraper DB. All include `id serial PK`, `created_at`, `updated_at`. FK to `properties.id`.

### New tables

**`appraiser_transfer_history`**
Prior deeds as listed by the county appraiser. Scout writes; Investigate Phase A verifies.
- `property_id` FK, `book`, `page`, `instrument_number`, `recorded_date`, `grantor_raw`, `grantee_raw`, `short_legal_raw`
- `verification_status`: pending | verified | verified_with_discrepancy | not_findable
- `verification_notes`, `verified_at`

**`rod_captures`**
Raw captures from Register of Deeds. **Immutable once written.**
- `property_id` FK, `source_url`
- `capture_type`: grantee_search_result | grantor_search_result | document_image | index_page
- `book`, `page`, `instrument_number` (nullable — what we think this is)
- `raw_content` (bytea or file path for PDF/image), `ocr_text`, `ocr_confidence`
- `captured_at`
- `parse_status`: captured | extracted | failed | needs_human
- `parse_error`

**`court_captures`**
Same structure as `rod_captures` + `court_case_number`, `document_type`.

**`document_extractions`**
Structured fields from one captured document. One row per parsed document.
- `rod_capture_id` FK (nullable), `court_capture_id` FK (nullable), `property_id` FK
- `document_type`: warranty_deed | quitclaim | corrective_deed | deed_of_distribution | deed_of_trust | mortgage | release | lis_pendens | judgment_lien | affidavit_of_death | estate_order | other
- `grantor_names` (jsonb), `grantee_names` (jsonb)
- `recorded_date`, `instrument_date`, `book`, `page`, `instrument_number`
- `vesting_language`, `legal_description_full`, `legal_description_short`, `plat_book`, `plat_page`
- `conveys_multiple_parcels` (bool), `references_prior_deed_book`, `references_prior_deed_page`
- `legal_match_to_parcel`: high | medium | low | none
- `legal_match_method`: plat_reference | metes_bounds | narrative | chain_logic_only
- `legal_match_notes`, `summary`, `flags` (jsonb)
- **Application-layer enforcement:** reject any insert without a valid capture_id reference

**`investigation_sessions`**
One row per property investigation.
- `property_id` FK, `status`: pending | in_progress | settled | flagged_for_review
- `current_phase`: A | B | C | D | E | done
- `started_at`, `completed_at`, `iteration_count`, `stop_reason`

**`investigation_questions`**
Open/resolved questions the investigator is chasing.
- `session_id` FK, `question` (text), `actions_taken` (jsonb)
- `resolution`: resolved | unresolved_flagged | abandoned
- `resolution_notes`

**`investigation_trace`**
Append-only audit log. Never update, only insert.
- `session_id` FK, `step_number`, `action`, `input` (jsonb), `output` (jsonb), `timestamp`

**`incidental_records`**
Mortgages, liens, releases, etc. found during investigation. Not chain-analyzed.
- `property_id` FK, `extraction_id` FK, `record_type`, `summary`

**`chain_conclusions`**
Final output per property. Supersede, never overwrite.
- `property_id` FK, `status`: active | superseded
- `current_owners` (jsonb — normalized names with deceased flags)
- `acquisition_type`: deed | inheritance_with_deed_of_distribution | inheritance_court_only | unresolved
- `acquisition_document_refs` (jsonb), `vesting`, `vesting_evidence`
- `legal_description_confidence`: high | medium | low
- `supporting_document_refs` (jsonb), `flags` (jsonb)
- `verify_status`: pending | approved | objection_raised | flagged_for_human
- `verify_objections` (jsonb, nullable)
- `superseded_by_id` FK → `chain_conclusions`

### Columns to add to `properties`
- `scout_completed_at`
- `investigation_status` (mirrors `investigation_sessions.status`)
- `chain_conclusion_id` FK → active `chain_conclusions` row

---

## Scraper Inventory

### `server.py` — Unified HTTP server on port 8000

| Route | Module | Status |
|-------|--------|--------|
| `POST /county/wake/assessor` | `county/wake/assessor/search.py` | Solid |
| `POST /county/wake/deeds` | `county/wake/deeds/search.py` | Solid (gaps below) |
| `POST /county/mecklenburg/assessor` | `county/mecklenburg/assessor/search.py` | Assessor only |
| `POST /county/newhanover/assessor` | `county/newhanover/assessor/search.py` | Assessor only |
| `POST /county/buncombe/assessor` | `county/buncombe/assessor/search.py` | Assessor only |
| `POST /skipgenie` | `skipgenieapi/client.py` | Working |
| `POST /court/nc/search` | `court/nc/search.py` | Built, not wired in n8n |
| `POST /court/nc/register_of_actions` | `court/nc/search.py` | Built, not tested end-to-end |

---

### Wake County Assessor — `county/wake/assessor/search.py`
**Status: Solid**

Functions: `search_by_owner`, `search_by_address`, `search_by_id`, `search_by_pin`, `get_account`

**Gaps:**
- Transfer history extraction is partial — depth depends on what the assessor page exposes
- No structured subdivision/block/lot parsing from legal description
- Plat book/page not always returned as separate fields

---

### Wake County Deeds (ROD) — `county/wake/deeds/search.py`
**Status: Solid — most capable scraper we have**

Functions: `search_by_name(surname, first_name, role, start_date, end_date, doc_types, page, fetch_details)`, `search_by_document`, `get_document`

**Gaps:**
- **No book/page direct search** — cannot look up "Book 1234, Page 567" directly; must go by name or document number. This is a **Phase A blocker** — appraiser history gives book/page refs.
- **No deed PDF download** — `get_document()` fetches the detail page but does not download the actual image/PDF. This is a **document-read blocker**.
- **No date filtering in n8n tool** — `start_date`/`end_date` exist in code but n8n tool node doesn't pass them
- **Page 1 only in n8n** — `page` parameter exists but AI always sends page=1; truncates owners with many deeds

---

### Mecklenburg / New Hanover / Buncombe Assessors
**Status: Assessor only — no deeds**

Assessor scrapers exist and work. The `deeds/` subfolder exists in each but contains only an empty `__init__.py`. ROD sites for these counties have not been researched or built.

---

### NC Courts Portal — `court/nc/search.py`
**Status: Built, not yet wired in n8n**

Functions: `search_by_name(name, county)`, `get_register_of_actions(case_url)`, `classify_foreclosure_stage(events)`, `is_tax_foreclosure(style)`

Session: `court/nc/session.py` — AWS WAF CAPTCHA requires manual solve once (real headed Chrome). `aws-waf-token` cached in `session_cookies.json` for ~48h. Run `python -m court.nc.session` to re-solve when expired.

**Gaps:**
- `get_register_of_actions()` not tested end-to-end in production
- Not wired as n8n tool node — AI agent cannot call it today
- No estate/probate-specific parsing (order of distribution, deed of distribution)
- CAPTCHA requires periodic manual renewal (~48h)

---

### SkipGenie — `skipgenieapi/client.py`
**Status: Working**

`lookup(first_name, last_name, middle_name, street_address, city, state, zip_code)` — returns phones, addresses, relatives.

---

## What's Missing: Gap Analysis

### Previously blocking — now built ✅

| Item | Status |
|------|--------|
| Wake ROD book/page direct search | ✅ Built — `search_by_book_page()` in `county/wake/deeds/search.py` |
| Deed PDF download | ✅ Built — `download_document_pdf()` fixed for Wake ROD 2026.1.2 |
| document-read subroutine (OCR + Claude extraction) | ✅ Built — `document_read/extract.py` + `document_read/pdf.py` |
| Database schema (all 9 tables) | ✅ Migrated — `database/migrations/001_chain_of_title.sql` + `002_properties_scout_fields.sql` |
| All 13 Investigate agent endpoints | ✅ Built — `investigate/handlers.py` + routes in `server.py` |
| `/investigate/pull-deed` (county-agnostic) | ✅ Built — dispatches to `_pull_deed_wake`; add more counties via `_COUNTY_DISPATCHERS` dict |
| `/scout/write` | ✅ Built — `scout/writer.py` |
| NC Courts wired as n8n tool nodes | ✅ Built — Court Search, Register of Actions, Court Pull all connected |

### Remaining gaps

| Missing piece | Needed for |
|---------------|-----------|
| Mecklenburg / New Hanover / Buncombe deeds scrapers | Phase A/B/C for non-Wake counties — `_COUNTY_DISPATCHERS` has stub slots |
| Conclude n8n node | Layer 3 — not yet built |
| Verify n8n node | Layer 4 — not yet built |
| Verify → Investigate loopback | Orchestration — not yet built |
| DB write-back to FPILS | Future handoff — deferred |
| Kimi LLM integration | Token cost reduction — blocked by n8n tool calling incompatibility |

---

## Build Order (from client spec)

1. **Schema migrations** — create all 9 new tables + add columns to `properties`
2. **document-read subroutine** — `rod_pull` + OCR + Prompt 2 extraction. Testable in isolation.
3. **Scout for Wake County** — wire existing assessor scraper to write to DB via Prompt 1. Validate appraiser data captures correctly.
4. **Investigate Phase A only** — verify appraiser-listed deeds. Validate correctly marks verified / discrepancy / not_findable.
5. **Investigate Phases B and C** — independent ROD search + one-hop chain-back. Regression test: **631 East Nelson Ave, Wake Forest NC** must reconstruct the 1941→1944→1954 chain.
6. **Investigate Phases D and E** — estate path + incidentals
7. **Conclude node**
8. **Verify node**
9. **Orchestration loop** — Verify → Investigate loopback, max one cycle per property
10. **Second county adapter** — validate the pattern generalizes beyond Wake

---

## Test Cases

| Property | Purpose |
|----------|---------|
| **631 East Nelson Ave, Wake Forest NC** | Corrective-deed case. 1941→1944→1954 chain. System must reconstruct via Phase B/C even if appraiser doesn't list all three deeds. **Primary regression test.** |
| Clean modern case (TBD) | One recent deed, clean chain-back, no complications. Smoke test. |
| Estate case (TBD) | Deceased owner, no successor deed, inheritance via NC Courts. Tests Phase D. |
| Cursive/handwritten deed (TBD) | Old deed, poor OCR confidence. Tests human-flag routing at `ocr_confidence < 0.75`. |

---

## File Map

```
server.py                          — unified HTTP server, all routes
county/
  wake/
    assessor/search.py             — SOLID
    deeds/search.py                — SOLID (missing: book/page search, PDF download)
    tax/search.py
  mecklenburg/
    assessor/search.py             — assessor only
    deeds/                         — EMPTY (not built)
  newhanover/
    assessor/search.py             — assessor only
    deeds/                         — EMPTY (not built)
  buncombe/
    assessor/search.py             — assessor only
    deeds/                         — EMPTY (not built)
court/
  nc/
    session.py                     — WAF token manager (manual CAPTCHA, 48h TTL)
    search.py                      — SmartSearch + ROA (built, not in n8n)
    session_cookies.json           — cached aws-waf-token
skipgenieapi/
  client.py                        — skip trace / people search
others/
  version 1.2.0/
    n8nsetup.md                    — current working n8n workflow JSON
    chain of title scraper build.md — client's 4-layer build spec
    chain of title ai prompt.md   — 5 AI prompts for each layer
    STATE.md                       — this file
```
