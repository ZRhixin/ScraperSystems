# Heir Tracer Workflow Guide

## What It Does
Automatically researches deceased property owners, identifies all legal heirs under NC Chapter 29 intestate succession, and calculates ownership shares — starting from just a property ID.

---

## Phase 1 — Session Start (runs once per property)

**Trigger:** POST to `/heir-tracer` with `property_id`, `county`, `state`.

1. **Root Owner Research** — Runs two searches on the root decedent:
   - SkipGenie: returns possible matches with relatives, addresses, deceased flag
   - Ancestry obituary collection (61843): finds the obituary, extracts named children
   - Outputs `relatives[]` (SkipGenie) + `ancestry_family_members[]` (Ancestry obit)

2. **Create Heir Session** — Opens a new session in the database.

3. **Seed Queue** — Unions both source lists, deduplicates by name, writes all unique persons to the research queue. This is why both SkipGenie and Ancestry are needed — each finds people the other misses.

4. **Trigger Worker** — Kicks off the worker loop asynchronously. Webhook returns immediately.

---

## Phase 2 — Worker Loop (runs once per queued person)

Processes one person at a time. Each iteration:

1. **Claim Next Person** — Pulls one name from the queue.

2. **SkipGenie (5 tries)** — Generates ranked search attempts (full name → initials → last only → no state). Stops at first attempt that returns results.

3. **Vital Status Researcher (VSR)** — Selects the best SkipGenie candidate using scoring rules (+3 relative overlap, +2 last name match, etc.). Then checks:
   - NC voter registration → Active = living, Removed = possibly deceased
   - Ancestry SSDI/death records if vital status uncertain
   - Saves voter record to DB

4. **Obituary Deep Diver (ODD)** — Searches for obituary and Ancestry records.
   - If confirmed living: skips Brave Search but still runs Ancestry and saves records
   - If deceased/unknown: full search — Brave Search + page fetch + Ancestry + save findings
   - High-confidence obituary can override a wrong "living" determination from VSR

5. **Surname Crosser (SCR)** — Searches Ancestry in parent-mode (`mother=` or `father=`) to find children who have different surnames (married daughters, etc.). Runs voter lookup to confirm found children.

6. **Title Attorney** — Researches deeds and court records:
   - Wake/Buncombe/Mecklenburg deed search as grantor
   - Court search for estate/probate cases (tries up to 3 name variants if first search fails)
   - If estate case found → downloads and extracts the probate PDF
   - Saves all findings to `heir_court_findings` via Write Court Findings (mandatory)

7. **Person Compiler** — Merges all data into a single person record with vital status, identity, cascade relatives, deed transfers, and estate facts.

8. **Write Person to DB** — Saves the complete record.

9. **Queue Cascade Relatives** — If person is deceased and no estate was found, queues their SkipGenie relatives (children/heirs) for research in the next loop iteration.

10. **Self Trigger Worker** — Re-fires the worker webhook to pick up the next person.

---

## Phase 3 — Family Assembly (runs once, when queue is empty)

1. **Family Assembler** — Loads all researched persons, full obituary texts, Ancestry records, and voter records for the session. Maps relationships to the root decedent (obituary language, Ancestry parent/child arrays, age gaps, relationship hints). Builds structured family tree JSON.

2. **Intestate Expert** — Applies NC Chapter 29:
   - Checks which heir line is active (children first, then spouse/parents/siblings)
   - For each deceased heir with unresearched relatives → triggers another worker cascade
   - Once all branches resolved → calculates fractional shares per stirpes

3. **Cascade loop** — If more persons need research, queues them and re-triggers the worker. Repeats until no unresolved branches.

4. **Genealogist** — Writes the final heir shares and closes the session via `Write Family Tree Database`.

---

## Data Flow Summary

```
Webhook
  └─ Root Owner Research (SkipGenie + Ancestry obit)
       └─ Seed Queue (union both sources)
            └─ Worker Loop × N persons
                 ├─ SkipGenie (5 tries)
                 ├─ VSR: voter + SSDI → vital status
                 ├─ ODD: obituary + Ancestry → saves records
                 ├─ SCR: parent-mode Ancestry → married-name children
                 ├─ Title Attorney: deeds + court + probate PDF
                 └─ Write Person → queue cascade if deceased
  └─ Family Assembler → Intestate Expert → Genealogist
```

---

## Key DB Tables

| Table | Written by |
|-------|-----------|
| `heir_research_sessions` | Create Heir Session |
| `heir_research_queue` | Seed Queue, Queue Cascade Relatives |
| `heir_research_persons` | Write Person to DB |
| `heir_voter_records` | VSR, SCR (Write Voter Record) |
| `heir_ancestry_records` | ODD, SCR (Write Ancestry Findings) |
| `heir_court_findings` | Title Attorney (Write Court Findings) |
| `heir_traces` | Genealogist (Write Family Tree Database) |

---

## Key Rules

- **Both SkipGenie and Ancestry are required** — SkipGenie finds people via address/phone networks; Ancestry finds people via official records (obituaries, death certs, census). Neither source alone is complete.
- **Obituaries are gold mines** — they name all children at once. The root decedent's obituary is the single most important document in the pipeline.
- **Probate documents are even better** — a filed estate lists heirs by name and address. Title Attorney must always attempt a pull when an estate case is found.
- **cascade_relatives come only from SkipGenie** — the Intestate Expert never invents new cascade targets from obituary text. Only SkipGenie-sourced relatives can trigger a cascade.
- **Session ID must be passed to all tool calls** — every write operation requires session_id + property_id for DB isolation.
