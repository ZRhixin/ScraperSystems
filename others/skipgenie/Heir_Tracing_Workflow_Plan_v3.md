# Heir Tracing Workflow — Restructured Plan (v3)

**Trusted Heir Solutions — Evidence-First Architecture**
**Date:** 2026-05-07

---

## Confirmed Decisions

| Decision | Choice |
|---|---|
| SkipGenie result | Always treated as a claim, not a fact — verified by two layers regardless of direction |
| Deceased verification | Waterfall: SSDI first → obituary fallback → stop at first confirmation. Need one source to confirm. |
| Alive verification | Same two layers: SSDI first → obituary check. Both must return nothing to confirm living. |
| Conflict — SkipGenie says alive but SSDI/obit finds death record | Flag as conflicting, add to gaps, status = manual_review for that branch |
| Conflict — SkipGenie says deceased but both layers find nothing | Cascade still proceeds, note saved: "SkipGenie only — no supporting document found" |
| Obituary tier | First layer — AI web search, available now, richest survivor data |
| SSDI tier | Second layer — FamilySearch API, scraper to be built, fires only if obituary finds nothing |
| Agent scope | Verification Agent runs for **every person** — living and deceased — not just deceased |
| Cascade depth | Unlimited — digs until every open branch resolves to a confirmed living person |
| Circular reference | Check added as safety — stops infinite loops on bad data |
| n8n execution mode | Main mode for now |

---

## Real-World Obituary Process (Operations Baseline)

This is the manual process the team runs today. The automation mirrors it step for step.

**Step 1 — Starting Signal**
A deceased owner is flagged in TitleMatrix (red + on People tab) when:
- SkipGenie marks the person as deceased, OR
- County records show the name as "NAME + HEIRS" or "ESTATE OF NAME" — meaning a death certificate is on file

Both signals map to `estate_path_unresolved = true` in our chain_conclusions table.

**Step 2 — Pull SkipGenie Data**
Before searching for an obituary, capture from SkipGenie:
- Approximate birth year
- Names of relatives (spouse, children, parents, siblings)
These are used to verify any obituary found is actually the right person.

**Step 3 — Search Google for Obituary**
Search: `[name] obituary [state]`. Add city if results are too broad.
- **Default:** use mailing address city/state
- **Fallback:** use property address city/state if no match found

**Step 4 — Verify the Match**
Cross-check any obituary found against SkipGenie data:
- Does the birth year line up?
- Do the listed survivors/relatives match SkipGenie relatives?

| Match Result | Confidence | Action |
|---|---|---|
| Both birth year AND relatives match | High | Confirmed — proceed |
| One of the two matches | Medium | Proceed, flag for review |
| Neither matches | Low | Likely wrong person — try different search or flag |

**Step 5 — Spouse Backdoor (when applicable)**
If a spouse appears on the deed OR in SkipGenie relatives:
- Search the spouse's name + obituary
- Scan for the target person as **"preceded in death by [name]"** or **"survived by [name]"**
- This confirms death even when the target's own obituary is hard to find

---

## The 5 Required Questions

| # | Question | Primary Source | Secondary Source | Agent Responsible |
|---|---|---|---|---|
| 1 | Date of Death | Obituary (explicit DOD) + SSDI (when built) | SkipGenie DOD field | Verification Agent |
| 2 | Marital status at death | Obituary ("survived by husband/wife") | SkipGenie spouse in relatives | Verification Agent |
| 3 | Was an estate/probate case filed? | NC Clerk of Superior Court | — | Court Research Agent |
| 4 | Did they have a will recorded? | NC Clerk — case type + Register of Actions | — | Court Research Agent |
| 5 | Which family members were alive when they died? | Obituary ("survived by children/parents/siblings") | SkipGenie possible_relatives | Verification Agent |

> **Key insight:** SkipGenie lists relatives but has no date context — it cannot confirm who was
> alive *at the moment of death*. An obituary's "survived by..." list directly answers Q5.
> SSDI gives government-confirmed DOD independent of SkipGenie for Q1.

---

## Data Sources

### Source 1 — SkipGenie (port 8001, existing)
- Returns: deceased flag, DOD (sometimes), addresses, phones, emails, possible_relatives
- **Role:** primary deceased trigger + contact info for living heirs + initial relatives list
- SkipGenie says alive → stop that branch. No further cost spent.
- SkipGenie says deceased → Deceased Researcher fires to find one supporting document

### Source 2 — Obituary Search (Verification Agent, web search tool — Tier 1 evidence)
- AI Agent with web search tool — works on any site: legacy.com, local newspapers, funeral home sites, findagrave.com, etc.
- **Tier:** first — richest source for survivor data, available now, no scraper needed
- **Role in waterfall:** called FIRST by Verification Agent. Verified match → evidence confirmed, stop. Do not call SSDI.
- **Best use:** Q1 (DOD), Q2 (marital status at death), Q5 (who survived the decedent)

**Search and verification sequence (mirrors operations manual process):**
1. Pull from SkipGenie first: birth year + relatives list (used to verify any obituary found is the right person)
2. Search: `"[first] [last]" obituary [state]` — default city from mailing address, fallback to property address
3. Cross-check any result against SkipGenie data:
   - Birth year matches AND relatives/survivors match → **high confidence**, confirmed, stop
   - Only one of the two matches → **medium confidence**, confirmed with flag, stop
   - Neither matches → wrong person, discard, try next result or different city
4. **Spouse backdoor** (when applicable): if spouse appears on deed or in SkipGenie relatives,
   also search `"[spouse name]" obituary [state]` and scan for the target person
   appearing as **"preceded in death by [name]"** or **"survived by [name]"** —
   this confirms death even when the target's own obituary is not directly findable

### Source 3 — SSDI via FamilySearch (port 8003, scraper to be built — Tier 2 evidence)
- Social Security Death Index — every death reported to the US Social Security Administration
- FamilySearch API: free with account, fast structured lookup
- Returns: government-confirmed DOD, last known ZIP code
- **Tier:** second — government record, authoritative, fires only if obituary search finds nothing
- **Role in waterfall:** called ONLY if obituary search finds nothing. If found → evidence confirmed, stop.
- **Status:** scraper to be built. Until then, Verification Agent stops after obituary search.

### Source 4 — NC Court Records (port 8000, existing)
- Returns: estate cases, will admissions, probate filings
- **Role:** Q3 (estate filed?) and Q4 (will recorded?) — exclusive to Court Research Agent
- Never used for root owner (Phase D already ran)

---

## Scrapers to Build

### ssdiscraper (port 8003) — build later

```
File: ssdiscraper/handler.py

POST http://127.0.0.1:8003
Input:  { first_name, last_name, state, approx_birth_year? }
Output: { found, dod, last_zip, confidence: "verified" }

Data source: FamilySearch API (free, needs API key)
Fallback:    Steve Morse One-Step SSDI (free scrape, no key needed)
```

When built, register it as a third tool on the Verification Agent.
No workflow changes needed — the agent will use it automatically.

---

## Agent Architecture (v3)

**5 agents total. No central orchestrator. The workflow graph coordinates all sequencing and fan-out.**

| Agent | Role | Tools | Called When |
|---|---|---|---|
| **Skip Tracer Agent** | Runs SkipGenie for any person. Returns deceased status, DOD, contact info, relatives. | SkipGenie HTTP (port 8001) | Every person: root owner, Level-1 heirs, all sub-heirs. Always runs first. |
| **Verification Agent** | Two-layer identity check for **every** heir regardless of SkipGenie's claim. Waterfall: obituary first → SSDI second. **Deceased path:** stops when one source confirms death. **Alive path:** both layers must return nothing to confirm living. Flags conflicts when layers disagree with SkipGenie. | Web Search Tool, HTTP Fetch Tool, SSDI HTTP (port 8003 — when built) | Every person — living and deceased. Runs after Skip Tracer for all heirs. |
| **Court Research Agent** | Searches NC court for estate/probate. Determines will vs intestate (Q3, Q4). | Court Search, Register of Actions | Only for confirmed deceased heirs in the cascade loop. Never for root owner (Phase D already ran). Runs as a standalone n8n node, not a sub-tool. |
| **Estate Analyst Agent** | Determines heirs + fractional shares. Two paths: Chapter 29 intestate or will-directed testate. Embeds full NC Chapter 29 rules. | None — pure reasoning | After Court Research returns estate_type for a deceased heir. Standalone n8n node. |
| **Heir Tree Compiler** | Assembles all cascade levels into final output. Validates share totals sum to 100%. | None — pure reasoning | Once. Final step only. |

---

## Evidence Record Structure

The Verification Agent runs the same two-layer waterfall for every person regardless of
SkipGenie's claim. The outcome interpretation differs by path.

---

### Deceased Path (SkipGenie says deceased)
Waterfall stops when one source confirms. Obituary first — SSDI only if obituary finds nothing.

**Scenario A — Obituary found and verified (first layer):**
```json
{
  "skipgenie_claim":           "deceased",
  "verification_result":       "confirmed_deceased",
  "supporting_document":       "obituary",
  "dod":                       "2010-03-15",
  "dod_source":                "obituary",
  "obituary_searched":         true,
  "obituary_url":              "https://www.legacy.com/obituaries/...",
  "obituary_snippet":          "Sharon Ann Hayes, 70, of Raleigh, NC passed away...",
  "obituary_match_confidence": "high",
  "obituary_birth_year_match": true,
  "obituary_relatives_match":  true,
  "found_via_spouse_search":   false,
  "marital_status_at_death":   "widowed",
  "survivors_from_obituary": [
    { "name": "Michael Hayes",  "relationship": "child" },
    { "name": "Jennifer Hayes", "relationship": "child" }
  ],
  "ssdi_checked":              false,
  "ssdi_last_zip":             null,
  "note":                      null
}
```

**Scenario A2 — Found via spouse backdoor (first layer):**
```json
{
  "skipgenie_claim":           "deceased",
  "verification_result":       "confirmed_deceased",
  "supporting_document":       "obituary_spouse_backdoor",
  "dod":                       null,
  "dod_source":                "spouse_obituary_mention",
  "obituary_searched":         true,
  "obituary_url":              "https://www.legacy.com/obituaries/robert-hayes...",
  "obituary_snippet":          "...preceded in death by his wife Sharon Ann Hayes...",
  "obituary_match_confidence": "medium",
  "found_via_spouse_search":   true,
  "spouse_searched":           "Robert Hayes",
  "marital_status_at_death":   "married",
  "survivors_from_obituary":   [],
  "ssdi_checked":              false,
  "note":                      "Target found as 'preceded in death by' in spouse Robert Hayes obituary."
}
```

**Scenario B — Obituary not found, SSDI confirms death (second layer):**
```json
{
  "skipgenie_claim":         "deceased",
  "verification_result":     "confirmed_deceased",
  "supporting_document":     "ssdi",
  "dod":                     "2010-03-15",
  "dod_source":              "ssdi",
  "obituary_searched":       true,
  "obituary_url":            null,
  "ssdi_checked":            true,
  "ssdi_last_zip":           "27601",
  "marital_status_at_death": null,
  "survivors_from_obituary": [],
  "note":                    null
}
```

**Scenario C — Both layers find nothing (SkipGenie only):**
```json
{
  "skipgenie_claim":         "deceased",
  "verification_result":     "unverified_deceased",
  "supporting_document":     null,
  "dod":                     "2010",
  "dod_source":              "skipgenie",
  "obituary_searched":       true,
  "ssdi_checked":            true,
  "note":                    "No supporting document found. Cascade proceeds — manual review recommended."
}
```

---

### Alive Path (SkipGenie says alive)
Both layers must return nothing. One hit from either = conflict.

**Scenario D — Both layers clear (confirmed living):**
```json
{
  "skipgenie_claim":         "alive",
  "verification_result":     "confirmed_alive",
  "supporting_document":     null,
  "ssdi_checked":            true,
  "ssdi_found":              false,
  "obituary_searched":       true,
  "obituary_found":          false,
  "note":                    null
}
```

**Scenario E — SSDI finds a death record (conflict):**
```json
{
  "skipgenie_claim":         "alive",
  "verification_result":     "conflict",
  "supporting_document":     "ssdi",
  "dod":                     "2023-07-04",
  "dod_source":              "ssdi",
  "obituary_searched":       false,
  "note":                    "CONFLICT: SkipGenie says alive but SSDI has a death record. Branch flagged for manual review."
}
```

**Scenario F — SSDI clear but obituary finds them deceased (conflict):**
```json
{
  "skipgenie_claim":         "alive",
  "verification_result":     "conflict",
  "supporting_document":     "obituary",
  "dod":                     "2023-07-04",
  "dod_source":              "obituary",
  "obituary_url":            "https://...",
  "obituary_searched":       true,
  "note":                    "CONFLICT: SkipGenie says alive but obituary found. Branch flagged for manual review."
}
```

---

**On conflicts (Scenarios E and F):**
- Branch does NOT continue automatically
- Heir is added to `gaps` with the conflict note
- `heir_traces.status` set to `manual_review`
- All other branches continue normally

**On unverified deceased (Scenario C):**
- Cascade continues — SkipGenie alone is enough to proceed
- Note is saved in the heir tree entry
- Does not trigger `manual_review` by itself

---

## Parallel Execution Map

```
PHASE 1 — PARALLEL (3 branches on webhook receive)
┌───────────────────────────────────────────────────┐
│  A: Postgres — Load chain_conclusion + Phase D    │
│  B: Skip Tracer — SkipGenie search: root owner   │
│  C: Verification Agent — Obituary search:         │
│     root owner (always deceased, fire immediately)│
└───────────────────────────────────────────────────┘
  ↓ all 3 complete → Merge
  ↓
PHASE 2 — SEQUENTIAL
  Estate Analyst: root owner (always intestate)
  Uses: obituary survivors list (Q5) + SkipGenie relatives (fallback)
  → Returns: heir list with fractional shares
  ↓
PHASE 3 — N8N AUTO-ITERATION (all Level-1 heirs, one at a time)
┌──────────────────────────────────────────────────────────┐
│  n8n passes each heir item through the pipeline:        │
│  Skip Tracer → Verification Agent → Code: Route Labels  │
│                                                          │
│  Verification Agent (per heir, after Skip Tracer):      │
│    SkipGenie says alive:   obit first → SSDI fallback.  │
│                            Both must return nothing.     │
│    SkipGenie says deceased: obit first → SSDI fallback. │
│                            One hit confirms.             │
└──────────────────────────────────────────────────────────┘
  ↓ Code: Separate Results reads all labeled items
  │
  ├─ confirmed_alive     → living heir, add to output, done
  ├─ confirmed_deceased  → deceased queue → Phase 4
  ├─ unverified_deceased → deceased queue → Phase 4 + note saved
  └─ conflict            → add to gaps, manual_review, done

PHASE 4 — EXPLICIT LOOP (Split In Batches with loop-back)
┌──────────────────────────────────────────────────────────────┐
│  Split In Batches: Cascade ← ← ← ← ← ← ← ← ← ← ← ←      │
│    (initial input: deceased queue from Phase 3)              │
│    (loop-back input: deceased sub-heirs from each iteration) │
│                                                              │
│  Per iteration — one deceased heir at a time:                │
│    1. Court Research Agent (NC court — Q3, Q4)               │
│    2. Estate Analyst Agent → sub-heir list with shares       │
│    3. For each sub-heir:                                     │
│         Skip Tracer → Verification Agent → Code: Route       │
│           confirmed_alive     → Code: Accumulate Living      │
│                                 (saved to static data)       │
│           confirmed_deceased  → loop-back to Split In Batches│
│           unverified_deceased → loop-back + note saved       │
│           conflict            → gaps, done                   │
│                                                              │
│  Split In Batches DONE output fires when queue is empty.     │
└──────────────────────────────────────────────────────────────┘
  ↓ Code: Read Cascade Results (reads static data)
  ↓
PHASE 5 — SEQUENTIAL
  Heir Tree Compiler → Code: Parse Output → Postgres: Write heir_traces
  ↓
PHASE 6 — SEQUENTIAL (FPILS Sync)
  Code: Build FPILS Payload
  → FPILS Sync Agent (HTTP calls to realestate backend, port 8000)
      1. GET property-people → find person_id for root deceased owner
      2. POST /api/v1/facts per deceased person (dod, marital status, will, probate)
      3. POST /api/v1/facts/{id}/evidence (obituary URL per confirmed fact)
      4. POST /api/v1/property-people/heirs per living heir (atomic: creates person + relationship)
      5. POST /computations/property/{id}/recompute
  → Postgres: Mark fpils_synced_at
  → Respond to Webhook
```

**Why this ordering is efficient:**
- Root owner is known deceased upfront → Verification Agent fires in Phase 1 with no waiting
- For all other heirs, SkipGenie runs first (fast, cheap) before spending on obituary/SSDI
- Phase 4 loop is visible in the n8n canvas — every step is a real node, easy to debug
- Living heirs never touch Court Research — no wasted calls
- FPILS sync runs after heir_traces is written — if sync fails, the trace is still saved and can be re-synced
- The loop-back connection in n8n means the graph handles recursion without an agent managing state

---

## Detailed Execution Flow

### Phase 1 — Root Owner Research (3 parallel branches)

**Branch A — Postgres: Load Context**
- Read `chain_conclusions` where `id = conclusion_id`
- Read `investigation_sessions` Phase D trace
- Output: Phase D text confirming estate_path_unresolved

**Branch B — Skip Tracer Agent: Root Owner**
- SkipGenie search: root owner name + state
- Root owner is known deceased — searching for DOD, possible_relatives, contact fragments
- Output: DOD (if available), possible_relatives list

**Branch C — Verification Agent: Root Owner**
- Root owner is confirmed deceased by definition (estate_path_unresolved trigger)
- Runs deceased path: obituary first → SSDI fallback → stop at first confirmation
- Obituary search: any site, any format — extract DOD, marital status, survivors list
- If obituary misses → SSDI check (when scraper available)
- If neither found → "SkipGenie only" note, cascade still proceeds
- Output: full evidence record including survivors list if obituary found (feeds Q2, Q5)

All 3 → Merge → continue

---

### Phase 2 — Determine Root Heirs (sequential)

**Estate Analyst Agent: Root Owner**
- estate_type: always "intestate" (confirmed by Phase D / estate_path_unresolved trigger)
- Survivor source priority: obituary survived_by list → SkipGenie possible_relatives → approx_death_year context
- Applies NC Chapter 29 (full rules embedded in system prompt)
- Output: heir list with fractional shares + statute applied

---

### Phase 3 — Trace and Verify All Level-1 Heirs

n8n auto-iterates each heir item through the pipeline. Per heir: Skip Tracer first, then Verification Agent.

**Skip Tracer Agent: per heir**
- SkipGenie search by name + state
- Returns: deceased flag, DOD, phones, emails, addresses, possible_relatives

**Verification Agent: per heir** (runs immediately after Skip Tracer for the same heir)
- Runs for EVERY heir — living or deceased
- Two-layer waterfall: obituary first → SSDI fallback
- Internal logic:
  - If SkipGenie said **deceased**: looking for ONE source to confirm → stop at first hit
  - If SkipGenie said **alive**: checking that NEITHER layer finds a death record

After Verification Agent returns → Code: Route Labels reads `verification_result` and tags each item.
Code: Separate Results (Run Once for All Items) collects all tagged items and splits them:

| Result | Action |
|---|---|
| `confirmed_alive` | Living heir. Add to `living_heirs` with SkipGenie contact info. Done. |
| `confirmed_deceased` | Added to deceased queue → enters Phase 4 loop. |
| `unverified_deceased` | Added to deceased queue → Phase 4 loop + note saved. |
| `conflict` | Add to `gaps`. Status = `manual_review`. Not cascaded. |

---

### Phase 4 — Cascade Loop (explicit n8n loop with loop-back)

The cascade is an explicit n8n loop built with Split In Batches and a loop-back connection.
There is no "Cascade Manager" agent. Every step is a visible n8n node.

**Split In Batches: Cascade**
- Initial input: deceased queue from Code: Separate Results (Level-1 deceased heirs)
- Loop-back input: deceased sub-heirs discovered in each iteration (Code: Accumulate Living feeds them back)
- Processes one item at a time (batch size = 1)
- When no more items come back, fires DONE output → exits loop

**Per iteration — each item is a confirmed or unverified deceased heir:**

**Step 1 — Court Research Agent**
- Q3: Search NC Clerk for estate/probate case (type E or SP)
- Q4: If case found → Register of Actions → check for will admitted to probate
- Returns: `estate_type` (testate | intestate), case details, will summary if testate
- If no case found: returns `estate_type = intestate` (default assumption)

**Step 2 — Estate Analyst Agent**
- Testate path: will beneficiary gets the deceased heir's full share_pct. Chapter 29 ignored.
- Intestate path: Chapter 29 applied using survivors from Phase 3 Verification evidence (obituary preferred, SkipGenie relatives fallback)
- Sub-heirs inherit fractions of THIS heir's share_pct (not the original 100%)
- Output: sub-heir list with fractional shares

**Step 3 — Sub-Heir Tracing (same pipeline as Phase 3)**
For each sub-heir returned by Estate Analyst, n8n auto-iterates:

- **Skip Tracer: Cascade** — SkipGenie lookup for the sub-heir
- **Verification: Cascade** — obituary → SSDI waterfall
- **Code: Route Cascade** — labels each sub-heir by verification_result
- **IF: Still Deceased?**
  - TRUE → **Code: Accumulate Living** saves any living sub-heirs from this batch to static data, then returns only the deceased sub-heirs → **these loop back to Split In Batches: Cascade**
  - FALSE (alive) → **Code: Accumulate Living** saves to static data, returns nothing → loop-back receives nothing for this item

**Circular Reference Check (inside Code: Route Cascade):**
Before allowing any sub-heir to loop back, check if their name already appears in the
`ancestor_names` list (passed down from the start and updated each iteration).
If match found → add gap: "Circular reference — [name] already in ancestry chain. Branch stopped."
Do not add to loop-back. Does not affect other branches.

**Split In Batches: Cascade — DONE output**
Fires when the queue is empty (no more deceased sub-heirs feeding back).
Continues to Code: Read Cascade Results.

**Code: Read Cascade Results**
Reads all accumulated living sub-heirs from static data.
Passes combined results to Code: Build Compiler Input.

---

### Phase 5 — Compile and Write

**Heir Tree Compiler Agent**
- Input: all living_heirs + deceased_in_chain records from every level
- Validates: sum of all `share_pct` in living_heirs = 100.0 (flags rounding gap if not)
- Validates: every deceased_in_chain entry has a non-empty `cascaded_to` list
- Attaches evidence record to every deceased_in_chain entry
- Returns: complete heir tree JSON

**Postgres: Write heir_traces**
- status = `complete` if no gaps
- status = `manual_review` if any gaps present
- status = `partial` if some branches unresolved

---

### Phase 6 — FPILS Sync

Runs after heir_traces is written. If sync fails, the trace is already saved and can be re-synced manually.

**Code: Build FPILS Payload**

Reads the compiled heir tree and builds two structured lists:

*Facts list* — one entry per fact per deceased person:
```json
[
  {
    "person_name":   "Sharon Hayes",
    "fact_type":     "date_of_death",
    "fact_value":    "2010-03-15",
    "confidence":    "verified",
    "evidence_url":  "https://www.legacy.com/obituaries/...",
    "evidence_desc": "Obituary — Sharon Ann Hayes"
  },
  {
    "person_name":  "Sharon Hayes",
    "fact_type":    "marital_status_at_death",
    "fact_value":   "widowed",
    "confidence":   "probable",
    "evidence_url": null
  }
]
```

Confidence rules:
- `verified` — obituary URL confirmed it OR SSDI confirmed it
- `probable` — SkipGenie only, OR extracted from obituary text without explicit statement
- Never post facts with `confidence = assumed` — leave those for the FPILS team to fill in manually

*Heirs list* — one entry per living heir:
```json
[
  {
    "first_name":               "Michael",
    "last_name":                "Hayes",
    "relationship_to_deceased": "child_of",
    "deceased_owner_name":      "Sharon Hayes",
    "ownership_percentage":     25.0,
    "phones":                   [{"phone_number": "(704) 555-1234", "phone_type": "mobile"}],
    "emails":                   [{"email": "michael@email.com"}]
  }
]
```

---

**FPILS Sync Agent**

Sequential HTTP calls to the realestate backend (`http://localhost:8000`). Requires auth token in headers.

**Call 1 — Find person_ids for all deceased people:**
```
GET /api/v1/property-people/property/{property_id}
```
Match each deceased person by name to get their `person_id`.
Root deceased owner will already exist as `person_type = owner`.
Cascade deceased heirs may not exist yet — skip facts for anyone not found (log as gap).

**Call 2 — Post facts (one per fact per deceased person):**
```
POST /api/v1/facts
{
  "property_id":  1,
  "person_id":    <matched person_id>,
  "fact_type":    "date_of_death",
  "fact_value":   "2010-03-15",
  "confidence":   "verified",
  "notes":        "Confirmed via obituary search"
}
```

Active-slot check: if a fact of the same type already exists as `active` for this person,
use `POST /api/v1/facts/{fact_id}/supersede` instead of creating a duplicate.

**Call 3 — Attach evidence to date_of_death facts where obituary URL exists:**
```
POST /api/v1/facts/{fact_id}/evidence
{
  "evidence_type": "other",
  "description":   "Obituary — Sharon Ann Hayes",
  "url":           "https://www.legacy.com/obituaries/..."
}
```

**Call 4 — Create each living heir (atomic: person + relationship + contacts):**
```
POST /api/v1/property-people/heirs
{
  "property_id":              1,
  "deceased_owner_id":        <person_id of who they inherit from>,
  "first_name":               "Michael",
  "last_name":                "Hayes",
  "relationship_to_deceased": "child_of",
  "phones":                   [...],
  "emails":                   [...],
  "ownership_percentage":     25.0
}
```

Note: `deceased_owner_id` must be the FPILS `person_id` of the direct deceased parent,
not always the root owner. Sharon Hayes's children → `deceased_owner_id` = Sharon's person_id.

**Call 5 — Trigger recompute:**
```
POST /computations/property/{property_id}/recompute
{ "assumption_set_id": null }
```
FPILS rule engine reads all posted facts and independently computes ownership shares.
Do NOT finalize — that is a manual step after a human reviews the computation and blockers.

---

**Postgres: Mark fpils_synced_at**
```sql
UPDATE heir_traces
SET fpils_synced_at = NOW(), updated_at = NOW()
WHERE id = {trace_id};
```

---

### FPILS Finalization (manual step — not automated)

After sync, a human reviews the FPILS computation in the realestate UI:
- Check blockers — hard blockers prevent finalization (missing facts, unverified confidence)
- Upgrade `probable` facts to `verified` if additional evidence is found
- Once all facts are `verified` and no blockers remain → finalize
- Finalization writes computed `share_percentage` → `property_people.ownership_percentage`

Facts likely to need manual upgrade before finalization:
- `marital_status_at_death` — often `probable` from obituary text
- `spouse_at_death` — often `probable` from SkipGenie relatives
- Any fact where only SkipGenie was the source

---

## Output Format

```json
{
  "property_id":        1,
  "conclusion_id":      3,
  "root_decedent":      "Lydia Hayes",
  "total_living_heirs": 3,
  "living_heirs": [
    {
      "name":              "Dennis Hayes",
      "relationship_path": "child of Lydia Hayes",
      "share_pct":         50.0,
      "share_fraction":    "1/2",
      "is_alive":          true,
      "estate_path":       "intestate from Lydia Hayes — GS 29-15 Priority 1",
      "phones":            ["(704) 743-6590"],
      "emails":            [],
      "best_address":      "720 N Craige St, Salisbury NC 28144",
      "contact_status":    "not_contacted"
    },
    {
      "name":              "Michael Hayes",
      "relationship_path": "child of Sharon Hayes → child of Lydia Hayes",
      "share_pct":         25.0,
      "share_fraction":    "1/4",
      "is_alive":          true,
      "estate_path":       "intestate from Sharon Hayes — GS 29-15 Priority 1",
      "phones":            [...],
      "emails":            [...],
      "best_address":      "...",
      "contact_status":    "not_contacted"
    }
  ],
  "deceased_in_chain": [
    {
      "name":            "Sharon Hayes",
      "dod":             "2010-03-15",
      "estate_type":     "intestate",
      "cascaded_to":     ["Michael Hayes", "Jennifer Hayes"],
      "evidence": {
        "evidence_sources":        ["skipgenie", "obituary"],
        "dod_source":              "obituary",
        "marital_status_at_death": "widowed",
        "obituary_url":            "https://www.legacy.com/obituaries/...",
        "survivors_from_obituary": [
          { "name": "Michael Hayes",  "relationship": "child" },
          { "name": "Jennifer Hayes", "relationship": "child" }
        ],
        "ssdi_confirmed": false,
        "note": null
      }
    }
  ],
  "gaps":         [],
  "credits_used": 4,
  "status":       "complete"
}
```

---

## DB Schema

```sql
CREATE TABLE heir_traces (
  id                  SERIAL PRIMARY KEY,
  property_id         INTEGER NOT NULL,
  conclusion_id       INTEGER NOT NULL REFERENCES chain_conclusions(id),
  root_decedent_name  TEXT NOT NULL,
  heir_tree           JSONB NOT NULL,
  living_heir_count   INTEGER,
  total_credits_used  INTEGER,
  status              TEXT DEFAULT 'draft',   -- draft | complete | manual_review | partial
  gaps                JSONB,
  fpils_synced_at     TIMESTAMPTZ,
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Workflow Node Summary

| # | Node | Phase |
|---|---|---|
| 1 | Webhook | Trigger |
| 2 | Postgres: Load Context | Phase 1A |
| 3 | Skip Tracer: Root Owner | Phase 1B |
| 4 | Verification: Root Owner | Phase 1C |
| 5 | Merge: Phase 1 | Phase 1 join |
| 6 | Estate Analyst: Root Owner | Phase 2 |
| 7 | Code: Parse Heir List | Phase 2 → 3 |
| 8 | Skip Tracer: Per Heir | Phase 3 |
| 9 | Verification: Per Heir | Phase 3 |
| 10 | Code: Route Labels | Phase 3 |
| 11 | Code: Separate Results | Phase 3 → 4 |
| 12 | IF: Any Deceased? | Phase 3 → 4 |
| 13 | Split In Batches: Cascade | Phase 4 loop start ← loop-back target |
| 14 | Court Research Agent | Phase 4 |
| 15 | Estate Analyst Agent | Phase 4 |
| 16 | Skip Tracer: Cascade | Phase 4 sub-heir |
| 17 | Verification: Cascade | Phase 4 sub-heir |
| 18 | Code: Route Cascade + Circular Check | Phase 4 sub-heir |
| 19 | IF: Still Deceased? | Phase 4 branch |
| 20 | Code: Accumulate Living | Phase 4 → loop-back |
| 21 | Code: Read Cascade Results | Phase 4 exit |
| 22 | Code: Build Compiler Input | Phase 4 → 5 |
| 23 | Heir Tree Compiler | Phase 5 |
| 24 | Code: Parse Output | Phase 5 |
| 25 | Postgres: Write heir_traces | Phase 5 |
| 26 | Code: Build FPILS Payload | Phase 6 |
| 27 | FPILS Sync Agent | Phase 6 |
| 28 | Postgres: Mark fpils_synced_at | Phase 6 |
| 29 | Respond to Webhook | Phase 6 |
| **Total** | | **29 nodes** |

**Tool nodes attached to agents (not in main flow):**
- Skip Tracer (Root + Per Heir + Cascade): SkipGenie HTTP tool on each (3 tool nodes)
- Verification (Root + Per Heir + Cascade): Web Search tool on each (3 tool nodes)
- Court Research Agent: Court Search HTTP + Register of Actions HTTP (2 tool nodes)
- FPILS Sync Agent: 5 HTTP tools (Get Property People, Post Fact, Post Evidence, Post Heir, Recompute)
- **Total tool nodes: 13 now, 14 when SSDI HTTP tool added to all 3 Verification nodes**

---

## Build Order

| Step | Task | Notes |
|---|---|---|
| 1 | Run `heir_traces` CREATE TABLE SQL | Prerequisite for everything |
| 2 | Confirm skipgenieapi running on port 8001 | Skip Tracer Agent prerequisite |
| 3 | Set up web search API key in n8n (SerpAPI or Brave Search) | Verification Agent — obituary search tool |
| 4 | Build n8n workflow Phases 1–5 (heir tracing only, no FPILS sync yet) | Obituary is the only evidence tool at this stage |
| 5 | Test with Lydia Hayes payload — verify heir_traces row written correctly | Validate end-to-end trace flow |
| 6 | Add Phase 6 FPILS Sync nodes to workflow | Confirm realestate backend URL + auth token |
| 7 | Test FPILS sync — verify facts posted, heirs created, recompute triggered | Check blockers in FPILS UI after sync |
| 8 | Build `ssdiscraper` (port 8003) using FamilySearch API | Tier 2 evidence — adds government DOD when obituary finds nothing |
| 9 | Register SSDI HTTP tool on all 3 Verification Agent nodes in n8n | Agent automatically falls back to SSDI when obituary finds nothing |
| 10 | Re-test full flow — verify obituary fires first, SSDI only on miss | Confirm waterfall order and FPILS sync still clean |
| 11 | Switch to Queue mode (Redis + workers) when ready for production | Enables true parallel execution across all branches |

> **Current state without SSDI scraper:** Verification Agent goes straight to obituary only.
> **Current state without FPILS sync:** heir_traces writes correctly but nothing syncs to realestate.
> Both can be added independently without restructuring the rest of the workflow.
