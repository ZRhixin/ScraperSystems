# Session Context — 2026-05-27
**Project:** TitleMatrix / Trusted Heir Solutions — ScraperSystems  
**Codebase:** `C:\Users\Summer Ishi\Github\TitleMatrix\ScraperSystems\`  
**Goal:** NC intestate heir tracing pipeline (multi-agent n8n + Python server)

---

## What We Built / Fixed This Session

### Overview
The heir tracing system is a multi-agent n8n workflow that researches NC property owners who died intestate and builds a family tree of legal heirs under NC Ch. 29. One workflow JSON (`workflow_v4_local.json`) contains four sub-workflows sharing a single n8n workflow context.

---

## Current Workflow State

**File:** `ScraperSystems/others/heirtracer/workflow_v4_local.json`  
**Build script:** `ScraperSystems/_build_workflow_v4.py`  
**Node count:** 62 nodes, 57 connections  
**Status:** BUILT but **NOT YET REIMPORTED into n8n**

To rebuild: `venv\Scripts\python.exe _build_workflow_v4.py` from ScraperSystems dir.  
Output always goes to `others/heirtracer/workflow_v4_local.json` — never the root.

---

## The Four Sub-Workflows (all in one n8n JSON)

### Workflow 1 — Root Research
**Trigger:** `Webhook` (path: configurable, `responseMode: "onReceived"`)  
**Flow:** `Webhook → Create Heir Session → Root Owner Research (agent) → Write Root Person → Queue Initial Relatives → Trigger Orchestrator Init`

- `Root Owner Research` is a v3 agent whose system prompt is patched in `_build_workflow_v4.py` using `re.sub()` with `DOTALL` (because the v3 JSON has `�` encoding artifacts that break `str.replace()`)
- `Write Root Person` saves the root decedent to `heir_research_persons`
- `Queue Initial Relatives` (**NEW this session**) calls `/heir/queue-persons` with ALL `cascade_relatives` from Root Owner Research, so all children/heirs are in the queue before the loop starts
- `Trigger Orchestrator Init` fires the orchestrator for the first queued person (reads `queue_id` from Queue Initial Relatives response)

### Workflow 2 — Orchestrator Loop
**Trigger:** `Orchestrator Webhook` (path: `heir-orchestrator`, `responseMode: "onReceived"`)  
**Flow:** `Orchestrator Webhook → Heir Research Orchestrator (agent) → Mark Person Done → Check Queue Status → If Queue Empty → [Self Trigger | Trigger Family Assembly]`

- Receives `{session_id, property_id, county, person_name, relationship_hint, queue_id}` in body
- Researches ONE person per invocation (SkipGenie → NC Voter → Ancestry → Court → Obit → synthesize)
- `Mark Person Done` calls `POST /heir/complete-person` with `queue_id` — if `queue_id` is null (root person), returns 200 no-op (fixed in `handlers.py`)
- `Check Queue Status` calls `POST /heir/next-person` → returns `{ item: { queue_id, person_name, ... } }` (**field name is `item`, not `next_person`** — this was a bug, fixed this session)
- `If Queue Empty` checks `$json.item?.person_name` — if exists → Self Trigger; if null → Trigger Family Assembly
- `Self Trigger Orchestrator` fires next person from `$('Check Queue Status (Orch)').first().json.item.*`

### Workflow 3 — Court Researcher Sub-Agent
**Trigger:** `Court Researcher Webhook` (path: `heir-court-researcher`, `responseMode: "lastNode"`)  
**Flow:** `Court Researcher Webhook → Court Researcher Agent → Return Court Result (respondToWebhook)`

- Called as an HTTP tool by the Orchestrator for every deceased person
- Runs Court Search → ROA → Document Pull → Write Court Findings
- Returns structured `{estate_filed, had_will, case_number, case_url, named_persons[], notes}`
- **Return Court Result** is the ONLY `respondToWebhook` node in the entire workflow (important — see pending issue below)

### Workflow 4 — Family Assembler
**Trigger:** `FA Webhook` (path: `heir-family-assembly`, `responseMode: "onReceived"`)  
**Flow:** `FA Webhook → Family Assembler (agent) → [Write Family Tree (FA)]`

- Fires when orchestrator queue is fully drained (`all_done = true`)
- Loads all person records, applies NC Ch. 29 intestate succession, writes final `heir_tree` to DB
- Key tools: `Load Family Dataset (FA)`, `Write Family Tree (FA)`
- `Write Family Tree (FA)` calls `POST /heir/write` with fields: `session_id`, `property_id`, `root_decedent_name`, `heir_tree` (array), `notes`

---

## Bugs Fixed This Session

### 1. cascade never happened — all children lost (critical)
**Root cause A:** `Trigger Orchestrator Init` only sent `relatives[0]` to the orchestrator and never queued `relatives[1:]`. Alyce Joye Hayes and Troy Hayes were never queued.  
**Root cause B:** `Check Queue Status` called `/heir/next-person` which returns `{ item: {...} }`, but the if-node checked `$json.next_person?.person_name`. Since `next_person` never exists, the queue always appeared empty → FA triggered after the first person.  
**Fix:** Added `Queue Initial Relatives` node (calls `/heir/queue-persons` with all cascade_relatives). Fixed field name `next_person` → `item` in `If Queue Empty (Orch)` and `Self Trigger Orchestrator`.

### 2. `queue_id is required` 400 error from `/heir/complete-person`
**Root cause:** Root person has no queue entry (started directly, not via queue). `complete_person()` required `queue_id`.  
**Fix:** `handlers.py` line ~622 — if `queue_id` is null, return 200 no-op `{"queue_id": null, "status": "done", "note": "no queue entry (root person)"}`. **Server must be restarted to apply.**

### 3. `root_decedent_name is required` from `/heir/write`
**Root cause:** FA agent sent `family_tree` field but endpoint expects `heir_tree`. Also missing `root_decedent_name`.  
**Fix:** Updated `Write Family Tree (FA)` tool in build script.

### 4. `Unused Respond to Webhook node found in the workflow` (500 error from Court Researcher)
**Root cause:** Workflow had two `respondToWebhook` nodes — `Return Court Result` (Court Researcher) and `Respond to Webhook` (Root Research). n8n finds the Root Research one "unused" from the Court Researcher execution context.  
**Fix:** Set main entry `Webhook` to `responseMode: "onReceived"`, removed the `Respond to Webhook` node entirely. Now `Return Court Result` is the only `respondToWebhook` node.  
**Status:** Fix is in the build script and JSON is rebuilt, but **workflow has NOT been reimported into n8n yet**. This is the current blocker.

### 5. FA webhook timeout (ECONNABORTED)
**Root cause:** FA Webhook was `responseMode: "lastNode"` — caller waited minutes for full run.  
**Fix:** Changed to `responseMode: "onReceived"`. Applied.

### 6. Root Owner Research missing SkipGenie address trick
**Root cause:** Orchestrator had it; Root Owner Research didn't.  
**Fix:** Patched via `re.sub()` in build script — agent now passes `street_address` + `zip_code` from Load Property State.

### 7. Census NC filter — wrong record selected
**Root cause:** Agent selected Lydia Hayes (NJ, born 1882) instead of NC record.  
**Fix:** Added hard-reject rule in step 4d: "Hard-reject any record whose birth_location or residence is outside North Carolina."

### 8. Step 4c parent-mode discovery (collection 61843 with mother=/father=)
**Root cause:** Passing `mother=` or `father=` to the obituary index (collection 61843) returns 39,000+ noise results.  
**Fix:** Patched system prompt to warn: DO NOT USE collection_id='61843' with mother= or father=.

### 9. Step 4d-b mandatory household followup + Ancestry Household Root tool
**Fix:** Added mandatory step: after finding a census record, call `Ancestry Household Root` with `source_url` to get all household members with `relationship_to_head`. Added new tool node to Root Owner Research.

---

## Pending Actions (must do before next test run)

1. **Reimport `others/heirtracer/workflow_v4_local.json` into n8n** — applies all fixes above, especially the cascade bug and Court Researcher 500 error.
2. **Restart the Python server** — applies the `queue_id=null` fix in `handlers.py`. Server runs `venv\Scripts\python.exe server.py` from ScraperSystems dir.
3. After reimport + restart: **run a new test session** for property 3 (Lydia L Hayes). Expect: Mary Justice (living, depth 1) → Alyce Joye Hayes (unknown, depth 1) → Troy Hayes (unknown, depth 1) → FA fires only after all 3 are done.

---

## Key Endpoints (Python server, port 8000)

| Endpoint | Purpose |
|---|---|
| `POST /heir/session` | Create a new research session |
| `POST /heir/upsert-person` | Insert or update a person record (progressive writes) |
| `POST /heir/write-person` | Final write for a person |
| `POST /heir/queue-persons` | Add persons to cascade queue (deduplicates) |
| `POST /heir/next-person` | Atomically claim next pending queue item → `{ item: {...} }` |
| `POST /heir/complete-person` | Mark queue item done (null queue_id = 200 no-op) |
| `POST /heir/queue-status` | Count by status; `all_done` when pending=0 + processing=0 + done>0 |
| `POST /heir/write` | Write final heir tree to `heir_traces` + update session |
| `POST /heir/persons` | Load all persons for a session |
| `POST /heir/filter-cascade` | Return only names not yet researched in this session |
| `POST /ancestry/household` | Fetch household members from a census record URL |
| `POST /skipgenie/search` | Search SkipGenie (paid — check DB first, save immediately after) |

---

## SkipGenie Security Constraint
SkipGenie is a **paid service** (per search). Rules enforced in agent prompts:
- Always check DB before calling (`Load Person` / `Load Ancestry Records`)
- Always save result immediately after calling
- Never call twice for the same person
- Daily cap: 200 searches (`DAILY_SEARCH_CAP=200` in `.env`)
- Credentials: `SKIPGENIE_EMAIL=tom@trustedheirsolutions.com` / `SKIPGENIE_PASSWORD=!jkL4Amn48rtQKQ`

---

## DB Tables (PostgreSQL)

| Table | Purpose |
|---|---|
| `heir_research_sessions` | One row per research run; tracks `status`, `heir_tree`, `intestate_analysis` |
| `heir_research_persons` | One row per researched person; `cascade_needed`, `orchestrator_output`, `research_phase` |
| `heir_research_queue` | Cascade queue; statuses: `pending → processing → done/failed`; `MAX_DEPTH = 5` |
| `heir_traces` | Final written heir trees from `/heir/write` |
| `heir_ancestry_records` | Saved Ancestry.com search results |
| `heir_voter_records` | NC voter registration lookups |
| `heir_court_findings` | Probate court document extractions |
| `heir_deed_findings` | Deed transfer findings |

---

## n8n Node IDs (NID) — all stable via `uuid5(NAMESPACE_URL, "heirtracer-v4-{name}")`

All node IDs are deterministically generated. If you need to reference a node ID, run:
```python
import uuid
nid = lambda tag: str(uuid.uuid5(uuid.NAMESPACE_URL, f"heirtracer-v4-{tag}"))
print(nid("Queue Initial Relatives"))
```

---

## Test Case: Property 3 — Lydia L Hayes
- **Address:** 631 E Nelson Ave, Wake Forest, NC 27587
- **Root decedent:** Lydia L Hayes (d. ~1997)
- **Three children (from obituary):**
  - Mary Justice — confirmed **living** (SkipGenie: MARY HAYES JUSTICE at 730 E Nelson Ave; voter: ACTIVE NCID EH24955)
  - Alyce Joye Hayes — **unknown** vital status (never researched, depth 1 queue)
  - Troy Hayes — **unknown** vital status (never researched, depth 1 queue)
- **Expected outcome:** FA should only fire after all 3 are researched. Tree should apply NC Ch. 29 per stirpes to any deceased children.
- **Sessions used so far:** 81 (root research test), 84 (Mary Justice only), 86 (premature FA — cascade bug), 87/88 (Court Researcher 500 error — pending reimport fix)

---

## Build Script Architecture Notes

- `_build_workflow_v4.py` — single file that generates the entire workflow JSON
- v3 nodes are reused via `v3node(name)` which reads from the v3 workflow JSON. The v3 JSON has `�` encoding artifacts (corrupted em-dashes) — patches to v3 system prompts must use `re.sub()` with `DOTALL`, not `str.replace()`
- Root Owner Research system prompt is patched in sections: SkipGenie step 2, step 4c (parent-mode warning), step 4d (census NC filter + household followup)
- `$fromAI()` syntax in n8n tool nodes: must be `={{ { "key": $fromAI("key", "desc") } }}` — NOT `"{{$fromAI(...)}}"` (causes "Unbalanced parentheses" error)
- All builds output to `others/heirtracer/workflow_v4_local.json` — hardcoded at bottom of build script

---

## Environment
- **OS:** Windows 11, PowerShell
- **Python venv:** `ScraperSystems/venv/Scripts/python.exe`
- **n8n:** localhost:5678 (npm global install)
- **Server:** `server.py` on port 8000 (must be running for all tool calls)
- **DB:** PostgreSQL (connection via `database/db.py`)
- **`.env` location:** `ScraperSystems/.env`
