# Heir Tracing Workflow — Game Plan (v2)

**Trusted Heir Solutions — n8n Multi-Agent Architecture**
**Scraper:** skipgenieapi (curl_cffi HTTP, port 8001)
**Proxy required:** IPRoyal residential rotating — VPS IP is blacklisted

---

## Changelog from v1
- Court Research Agent clarified: **not needed for root deceased owner** (Phase D already ran it). Only fires during cascade for deceased heirs.
- Cascade logic corrected: deceased heirs are **not assumed intestate**. Must check for will first. Will found → follow will directives. No will → apply Chapter 29.
- Intestate Analyst Agent renamed to **Estate Analyst Agent** — handles both intestate (Chapter 29) and testate (will-directed) paths.
- chain_conclusions confirmed to store **no structured court data** — only the `estate_path_unresolved` flag. FPILS facts must come from heir tracing's own court searches.
- Phase D reuse: root deceased owner court result is read from `investigation_sessions` trace, not re-searched.

---

## 1. Trigger Condition

Workflow starts when ALL of the following are true on a chain_conclusion:
- Senior Partner `verdict = approved`
- At least one `current_owners` entry has `estate_path_unresolved = true`
- Deceased owner has a name and last known county/state

Input payload:
```json
{
  "property_id":       1,
  "conclusion_id":     3,
  "session_id":        1,
  "deceased_owner":    "Lydia Hayes",
  "last_known_county": "Wake",
  "last_known_state":  "NC",
  "approx_death_year": "1954"
}
```

> **Note:** `estate_path_unresolved = true` already tells us the root deceased owner had no
> estate case and no will recorded. This was confirmed by Phase D. We do NOT re-run
> court search for the root owner.

---

## 2. Agent Architecture

5 agents total — 1 orchestrator, 4 specialists.

| Agent | Role | Tools |
|---|---|---|
| **Heir Orchestrator** | Top-level coordinator. Receives lead, dispatches sub-agents, handles cascade branching (will vs intestate), compiles final output. | All sub-agent tools |
| **Skip Tracer Agent** | Calls skipgenieapi to look up a person by name + state. Returns DOD, addresses, phones, emails, possible relatives. | POST http://127.0.0.1:8001 |
| **Court Research Agent** | Checks county court for a DECEASED HEIR's estate/probate case. Determines will vs. intestate. **Only called during cascade — never for the root deceased owner.** | Existing court search API |
| **Estate Analyst Agent** | Two paths: (1) If will exists → extract real property beneficiaries from will directives. (2) If no will → apply NC Chapter 29 intestate rules. Outputs heir list with fractional shares either way. | No external tools — pure reasoning from embedded Chapter 29 rules + will directives |
| **Heir Tree Compiler** | Takes all traced heirs across all cascade levels and builds the final structured output. | Write to heir_traces table |

---

## 3. Execution Flow

### Root Level vs Cascade Level

There are two entry points into the investigation loop:

| | Root Deceased Owner | Cascade Deceased Heir |
|---|---|---|
| Court search needed? | **NO** — Phase D already confirmed no estate, no will | **YES** — must check if this heir had their own will |
| Source of court findings | Read from `investigation_sessions` Phase D trace | Run fresh Court Research Agent |
| Assumed result | Always intestate (estate_path_unresolved = trigger condition) | Unknown — could be testate or intestate |
| Estate Analyst path | Always Chapter 29 | Will-directed OR Chapter 29 depending on court result |

---

### Phase 1 — Load Root Owner Context (No Court Search)

Read existing Phase D results directly from the database.

```json
{
  "confirmed_dod":       "1954-MM-DD",
  "marital_status":      "unknown",
  "probate_filed":       false,
  "will_exists":         false,
  "phase_d_trace":       "Court Expert returned no estate cases for HAYES, LYDIA in Wake County",
  "possible_relatives":  []
}
```

**Then run Phase 1A (Skip Trace) in parallel with loading context:**
- Skip Tracer Agent searches the root deceased owner → gets DOD, possible relatives, last addresses
- Relatives list is the primary source for identifying who was alive at death

---

### Phase 2 — Determine Heirs (Estate Analyst Agent)

**Root level always goes intestate path** since estate_path_unresolved is confirmed.

Applies NC Chapter 29 rules:
```json
{
  "statute_applied": "GS 29-14 + GS 29-15",
  "path":            "intestate",
  "heirs": [
    {
      "name":              "Dennis Hayes",
      "relationship":      "child",
      "share_numerator":   1,
      "share_denominator": 2,
      "share_pct":         50.0,
      "basis":             "Priority 1 — child of decedent"
    },
    {
      "name":              "Sharon Hayes",
      "relationship":      "child",
      "share_numerator":   1,
      "share_denominator": 2,
      "share_pct":         50.0,
      "basis":             "Priority 1 — child of decedent"
    }
  ]
}
```

---

### Phase 3 — Trace All Heirs in Parallel

**PARALLEL** — all heirs searched simultaneously via n8n Split In Batches.

Skip Tracer Agent fires one SkipGenie search per heir simultaneously. Returns for each:

```json
{
  "name":        "Sharon Hayes",
  "is_deceased": true,
  "dod":         "2010-03-15",
  "phones":      [],
  "emails":      [],
  "addresses":   [...],
  "relatives":   [...],
  "share_pct":   50.0
}
```

---

### Phase 4 — Cascade: Will Check BEFORE Chapter 29

For every heir where `is_deceased = true`, run the full cascade loop:

```
Deceased heir found (e.g. Sharon Hayes, died 2010)
  │
  ├─ Step 4A: Court Research Agent — search for Sharon Hayes estate/probate in county court
  │
  ├─ BRANCH: Did Sharon Hayes have a will admitted to probate?
  │
  │    YES — TESTATE PATH
  │    └─ Estate Analyst Agent reads will directives
  │         → Identifies who Sharon named for real property
  │         → That person inherits Sharon's 1/2 share
  │         → Could be ANYONE — Person Z, a charity, a trust
  │         → Does NOT have to follow family lines
  │
  └─ NO — INTESTATE PATH
       └─ Estate Analyst Agent applies Chapter 29
            → Sharon's 1/2 share divided among Sharon's own heirs
            → Spouse, children, parents, siblings in priority order
            → Each sub-heir gets a fractional slice of Sharon's 1/2
```

**This cascade repeats recursively** for any sub-heir who is also deceased.

---

### Phase 4 Share Calculation Example

```
Original owner (Lydia Hayes) dies 1954 — intestate
  ├─ Dennis Hayes → 1/2 share — LIVING → trace complete
  └─ Sharon Hayes → 1/2 share — DECEASED 2010
       │
       ├─ Sharon had a will → named Person Z for all real property
       │    └─ Person Z → 1/2 share — LIVING → trace complete
       │
       OR
       │
       └─ Sharon had no will → Chapter 29 → survived by 2 children
            ├─ Child A → 1/4 share (1/2 of Sharon's 1/2)
            └─ Child B → 1/4 share (1/2 of Sharon's 1/2)
```

---

### Phase 5 — Compile Heir Tree

Heir Tree Compiler assembles every generation into the final output:

```json
{
  "property_id":    1,
  "conclusion_id":  3,
  "root_decedent":  "Lydia Hayes",
  "total_living_heirs": 3,
  "living_heirs": [
    {
      "name":              "Dennis Hayes",
      "relationship_path": "child of Lydia Hayes",
      "share_pct":         50.0,
      "share_fraction":    "1/2",
      "is_alive":          true,
      "estate_path":       "intestate from Lydia Hayes",
      "phones":            ["(704) 743-6590"],
      "emails":            ["..."],
      "best_address":      "720 N Craige St, Salisbury NC 28144",
      "contact_status":    "not_contacted"
    },
    {
      "name":              "Person Z",
      "relationship_path": "beneficiary of Sharon Hayes will → child of Lydia Hayes",
      "share_pct":         50.0,
      "share_fraction":    "1/2",
      "is_alive":          true,
      "estate_path":       "testate — Sharon Hayes will dated 2005",
      "phones":            [...],
      "emails":            [...],
      "best_address":      "...",
      "contact_status":    "not_contacted"
    }
  ],
  "deceased_in_chain": [
    {
      "name":         "Sharon Hayes",
      "dod":          "2010-03-15",
      "estate_type":  "testate",
      "will_date":    "2005-06-01",
      "cascaded_to":  ["Person Z"]
    }
  ],
  "gaps": [
    "Sharon Hayes will content not fully parsed — beneficiary assumed from court record"
  ],
  "credits_used": 4
}
```

---

## 4. Parallel Execution Summary

| Phase | Parallel? | Method |
|---|---|---|
| Phase 1 (load context) + Phase 1A (Skip Trace) | Yes | Run simultaneously |
| Phase 3 — Trace all heirs | Yes | Split In Batches — all at once |
| Phase 4 — Multiple deceased heirs | Yes per heir | Each spawns independent cascade sub-flow |
| Phase 4A + 4 Skip Trace (per cascade) | Yes | Court search + SkipGenie fire together |
| Phase 1 → 2 (Analysis after research) | No — sequential | Needs Phase 1 results first |
| Phase 2 → 3 (Trace after heir list) | No — sequential | Needs heir list before tracing |

---

## 5. n8n Node Layout

```
Webhook
  └─ Load Context (GET chain_conclusion + investigation_sessions Phase D trace)
       └─ Heir Orchestrator Agent
            ├─ Tool: SkipGenie Search          → POST :8001
            ├─ Tool: Court Search              → existing court API (cascade only)
            ├─ Tool: Log Trace Step            → investigation_sessions
            └─ Tool: Write Heir Tree           → POST /heir-trace/write

            [Phase 3 fan-out]
            Split In Batches (one per heir)
              └─ SkipGenie Search (parallel)
            Merge Node

            [Phase 4 cascade check]
            IF node: any heir is_deceased?
              ├─ Court Research Agent (per deceased heir)
              └─ BRANCH: will found?
                   ├─ YES → Estate Analyst (testate path)
                   └─ NO  → Estate Analyst (Chapter 29 path)
              └─ Loop: trace new heirs → repeat cascade check

            Heir Tree Compiler Agent
              └─ Write Output → heir_traces table
```

---

## 6. SkipGenie API Contract (port 8001)

**Request:**
```json
POST http://127.0.0.1:8001
{
  "first_name":   "Sharon",
  "last_name":    "Hayes",
  "middle_name":  "",
  "city":         "",
  "state":        "NC",
  "zip_code":     ""
}
```

**Key response fields:**
```json
{
  "subject_name":       "SHARON ANN HAYES",
  "dod":                "2010-03-15",
  "deceased":           true,
  "addresses":          [...],
  "phones":             [...],
  "emails":             [...],
  "possible_relatives": [...],
  "credits_remaining":  95
}
```

> **Important:** skipgenieapi returns only the first (best) match. If age or location
> doesn't match the expected person, the Orchestrator flags it as a gap and marks
> that heir for manual review. Do NOT assume the first result is always correct.

---

## 7. Estate Analyst Agent — Two Paths

### Path A — Intestate (Chapter 29)
Triggered when: `will_exists = false` OR root level (estate_path_unresolved confirmed by Phase D).

Applies NC Chapter 29 priority order:
1. Surviving spouse (GS 29-14 share first)
2. Children and descendants per stirpes (GS 29-15 Priority 1)
3. Parents (Priority 2)
4. Siblings (Priority 3)
5. Grandparents / Aunts / Uncles (Priority 4)
6. Collateral to 5 degrees (Priority 5)
7. Escheat

Date of death determines dollar thresholds (pre-2012: $30K/$50K / post-2012: $60K/$100K).

### Path B — Testate (Will-Directed)
Triggered when: court search returns a will admitted to probate for a cascade-level deceased heir.

Estate Analyst reads will directives and identifies:
- Who was named as beneficiary for real property specifically
- What fractional share or specific bequest was made
- Whether a trust was named (requires further research)
- Whether the named beneficiary is still alive

> **Key rule:** A will can leave a property interest to ANYONE — family or not.
> Person A inherited 1/2 of a property intestate, then wrote a will leaving
> everything to Person Z (a friend, charity, or non-relative). Person Z now
> owns that 1/2 share. Chapter 29 does not apply to Person A's share at all.

---

## 8. New DB Table — heir_traces

```sql
CREATE TABLE heir_traces (
  id                  SERIAL PRIMARY KEY,
  property_id         INTEGER NOT NULL,
  conclusion_id       INTEGER NOT NULL REFERENCES chain_conclusions(id),
  root_decedent_name  TEXT NOT NULL,
  heir_tree           JSONB NOT NULL,
  living_heir_count   INTEGER,
  total_credits_used  INTEGER,
  status              TEXT DEFAULT 'draft',   -- draft | complete | manual_review
  gaps                JSONB,
  fpils_synced_at     TIMESTAMPTZ,            -- null until FPILS sync is built
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 9. FPILS Data Structure — Future Sync Reference

> Workflow will be tested and validated BEFORE connecting to FPILS.

**Facts to POST to `/api/v1/facts` per deceased person:**

| fact_type | fact_value | Source | confidence |
|---|---|---|---|
| `date_of_death` | YYYY-MM-DD | SkipGenie DOD | verified / probable |
| `marital_status_at_death` | married / single / widowed | SkipGenie relatives | probable |
| `spouse_at_death` | spouse person_id | SkipGenie relatives | probable |
| `probate_case_filed` | true / false | Court Research Agent (cascade) or Phase D (root) | verified |
| `probate_case_reference` | case number string | Court Research Agent | verified |
| `will_exists` | true / false | Court Research Agent (cascade) or Phase D (root) | verified |
| `will_admitted_to_probate` | true / false | Court Research Agent | verified |
| `will_directives` | beneficiary + share from will | Estate Analyst (testate path) | verified |
| `has_children` | true / false | SkipGenie + Estate Analyst | probable |
| `is_alive` | false | SkipGenie DOD / chain conclusion | verified |

**Fields to POST to `/api/v1/property-people/heirs` per living heir:**

| Field | Value | Source |
|---|---|---|
| `full_name` | SkipGenie subject_name | Skip Tracer |
| `person_type` | heir | always |
| `ownership_percentage` | share_pct float | Estate Analyst |
| `primary_phone` | best phone | Skip Tracer |
| `primary_email` | best email | Skip Tracer |
| `mailing_street/city/state/zip` | best address | Skip Tracer |
| `possible_relatives` | JSON array | Skip Tracer |

**Trigger computation after sync:**
```
POST /api/v1/computations/property/{property_id}/recompute
{ "assumption_set_id": null }
```

---

## 10. Testing Plan

| Test Case | Input | Pass Condition |
|---|---|---|
| Property 3 — Lydia Hayes (root, intestate) | Lydia Hayes, Wake NC, ~1954 | At least 1 living heir with phone/address returned |
| Cascade — heir also deceased, no will | Deceased heir with no probate | Chapter 29 applied to heir's estate, sub-heirs appear with correct fractional shares |
| Cascade — heir deceased WITH will | Deceased heir with will on record | Will beneficiary identified, Chapter 29 NOT applied, Person Z appears in heir tree |
| Non-family will beneficiary | Will leaves share to charity or friend | Correct person/entity in output, flagged for manual review if not traceable via SkipGenie |
| No SkipGenie match | Obscure name, no results | Gap logged, status = manual_review, no crash |
| Credits cap (200/day) | Trigger daily cap | daily_cap_reached handled gracefully, workflow pauses |
| Parallel trace | 3 heirs from one decedent | All 3 searched simultaneously |

---

## 11. Open Questions Before Build

- **Proxy** — IPRoyal credentials needed before going live on VPS. Test from local machine until then.
- **Multiple SkipGenie results** — API returns only first match. Need disambiguation logic or manual flag when wrong person returned.
- **Will content parsing** — Court search returns case metadata, not the will text itself. How do we read will directives? Does court capture include the will document, or does Estate Analyst have to infer from case summary?
- **Trust beneficiaries** — If a will leaves the share to a trust, the trust beneficiaries need further research. Not in scope for v1.
- **FPILS property ID mapping** — Need to match scraperstesting property to realestate system by parcel_id or address when syncing.
- **Cascade depth** — 5-generation limit proposed. Confirm with client.
- **Reuse Phase D or re-search?** — Currently plan is to read Phase D trace from investigation_sessions for root owner. Confirm this is accessible from heir tracing workflow trigger.
