# Heir Tracer — Current Workflow (v3)

> **Status:** As-built. This documents the actual sequence of nodes executing in the live n8n workflow.

---

## Overview

Three separate workflows run in sequence. Each is a rigid linear pipeline — every node fires in a fixed order and hands its output to the next node. No node can go back to gather more information once it has passed its turn.

```
Webhook → [Workflow 1: Root Research] → [Workflow 2: Worker Loop] → [Workflow 3: Family Assembly]
```

---

## Workflow 1 — Root Owner Research

**Trigger:** HTTP webhook (property_id, county, state)

**Purpose:** Research the deceased property owner. Identify their obituary, probate case, and
initial heir list.

### Sequence

| Step | Node | What it does |
|------|------|-------------|
| 1 | `Create Heir Session` | Creates a session record in DB. Returns session_id, property_id, county. |
| 2 | `Root Owner Research` (Agent) | Main research agent. Runs all steps below via tools. |
| 2a | → `Load Property State` | Loads property address, owner name, county. |
| 2b | → `SkipGenie — Root Decedent` | Searches SkipGenie for the owner. Optional — continues if no match. |
| 2c | → `NC Voter Root` | NC voter registration lookup. |
| 2d | → `Ancestry Search Save Root` | Searches obituary collection (61843) + saves results to DB. |
| 2e | → `Ancestry Record Root` | Fetches detail page of best obit hit (canonical children list). |
| 2f | → `Ancestry Search Save Root` (parent-mode) | Finds children with married surnames. |
| 2g | → `Ancestry Search Save Root` (census) | 1940 census search for household members. |
| 2h | → `Brave Search Root` | Web search for obituary on public sites. |
| 2i | → `Fetch Obit Root` | Fetches full obit text from public URL (if found). |
| 2j | → `Court Search Root` | NC Courts SmartSearch for estate/probate case. |
| 2k | → `Register Actions Root` | Register of Actions for any estate case found. |
| 2l | → `Court Doc Root` | Pulls and extracts probate document (family tree, named heirs). |
| 2m | → `Write Court Root` | Persists court findings to DB. |
| 3 | `Write Root Person` | HTTP node (not agent). Parses agent JSON output, writes root decedent to `heir_research_persons`. |
| 4 | `Branch Planner` (Agent) | Reads ancestry records + court findings from DB, seeds the initial heir queue. |
| 4a | → `Load Ancestry Records (BP)` | All ancestry records for the session (all collections). |
| 4b | → `Load Court Findings (BP)` | Any probate findings for the session. |
| 4c | → `Ancestry Search (BP)` | Parent-mode search for unresolved single-token names. |
| 4d | → `Queue Initial Heirs` | Writes initial heir list to `heir_research_queue`. |
| 5 | `Trigger Worker Init` | HTTP POST to worker webhook to start the loop. |

**Known issues with this workflow:**
- Branch Planner receives SkipGenie relatives from root research and treats them as potential children, even though SkipGenie has no basis for inferring parent-child relationships.
- `obituary_named_survivors` field on the root person record is never populated — Write Root Person does not send it.
- If a child's name is different from the root's last name (married daughter), it may be dropped.

---

## Workflow 2 — Worker Loop (Heir Research)

**Trigger:** Worker Webhook (session_id, property_id, county)

**Purpose:** Research one person from the queue. Determine vital status, find estate/probate,
decide whether to cascade to their children.

The loop runs once per queue item. Each completion re-triggers the worker for the next item.

### Sequence

| Step | Node | What it does |
|------|------|-------------|
| 1 | `Claim Next Person` | Marks the next pending queue item as `processing`. Returns person_name, queue_id. |
| 2 | `If Person Claimed` | If no item was claimed (queue empty), routes to family assembly. |
| 3 | `Worker - Prepare Item` | Formats input for Parse Attempts. Passes name, session_id, property_id, county. |
| 4 | `Parse Attempts` | JS code node. Generates 5 SkipGenie search attempts (county-narrowed first, then state-only fallback). |
| 5 | `SkipGenie Try 1` | SkipGenie search attempt 1 (full name + county). |
| 6 | `Got Results 1?` | If results found → SG Analyzer. If not → Try 2. |
| 7 | `SkipGenie Try 2–5` | Progressive fallback attempts (first only, state-only, last-only, etc.). |
| 8 | `SG Analyzer` (Agent) | Selects best candidate from SkipGenie results. Scores by geography, deceased status, relative overlap. Outputs matched_identity + cascade_relatives (all labeled "relative", never "child"). |
| 9 | `Parse SG Analyzer` | JS code node. Extracts JSON from agent output. |
| 10 | `Upsert Person SG` | Writes matched_identity to `heir_research_persons`. Creates person record. |
| 11 | `Vital Status Researcher` (Agent) | Determines if the person is living or deceased. Uses NC Voter lookup and Ancestry SSDI. |
| 11a | → `NC Voter (VSR)` | NC voter registration lookup by name. |
| 11b | → `Ancestry Search (VSR)` | SSDI / death index search. |
| 11c | → `Write Voter Record (VSR)` | Persists voter record to DB. |
| 12 | `Parse Vital Status` | JS code node. Extracts vital_status and confidence. |
| 13 | `Vital Status Gate` | If vital_status = unknown → flag person as paused, skip to next queue item. If known → continue. |
| 14 | `Obituary Deep Diver` (Agent) | Searches for obituary. Extracts survivors list. Writes ancestry records to DB. |
| 14a | → `Brave Search` | Web search for obituary. |
| 14b | → `Fetch Obituary Page` | Fetches full obit text. |
| 14c | → `Ancestry Search (ODD)` | Ancestry obit collection search. |
| 14d | → `Ancestry Record (ODD)` | Fetches detail page for canonical children list. |
| 14e | → `Write Ancestry Findings` | Persists ancestry records to DB. |
| 14f | → `NC Voter Lookup` | NC voter lookup for identity confirmation. |
| 15 | `Parse Obit Deep` | JS code node. Extracts obit findings JSON. |
| 16 | `Surname Crosser` (Agent) | Searches for children under married surnames. Cross-references voter rolls. |
| 16a | → `Ancestry Search (SCR)` | Parent-mode search for children with different surnames. |
| 16b | → `NC Voter (SCR)` | Voter lookup for identified children. |
| 16c | → `Write Voter Record (SCR)` | Persists voter records to DB. |
| 17 | `Parse Surname Crosser` | JS code node. Extracts married-name children. |
| 18 | `Title Attorney` (Agent) | Deed check + court search for estate. Pulls probate document if estate found. |
| 18a | → `Wake/Buncombe/Mecklenburg Deeds` | Deed search for this person as grantor. |
| 18b | → `Court Search` | NC Courts search for estate/probate case. Tries name variants. |
| 18c | → `Register of Actions` | ROA for any estate case. |
| 18d | → `Court Document Pull` | Extracts probate PDF (family tree, named heirs). |
| 18e | → `Write Court Findings` | Persists probate findings to DB. |
| 19 | `Person Compiler` (Agent) | Integrates all research. Loads ancestry + court + voter from DB. Writes final person record. |
| 19a | → `Load Ancestry Records (PC)` | All ancestry records for this session + person. |
| 19b | → `Load Court Findings (PC)` | Court/probate findings for this person. |
| 19c | → `Load Voter Records (PC)` | Voter records for this person. |
| 19d | → `Write Person (PC)` | Writes final `vital_status`, `cascade_needed`, `cascade_relatives`, `estate_filed` to DB. |
| 20 | `Parse Person Compiler` | JS code node. Extracts person record for Branch Decision. |
| 21 | `Branch Decision` (Agent) | Applies NC Ch. 29. If cascade_needed=true → queues children. |
| 21a | → `Load Person (BD)` | Loads person record from DB. |
| 21b | → `Queue Cascade (BD)` | Writes children to `heir_research_queue`. |
| 22 | `Mark Person Done` | Marks queue item as `done`. |
| 23 | `Self Trigger Worker` | HTTP POST to re-trigger worker webhook for next queue item. |
| 24 | `Check Queue Status` | After each completion, checks if queue is empty. |
| 25 | `If Queue Empty` | If empty → trigger Family Assembly. If not → Self Trigger Worker. |

**Known issues with this workflow:**
- Rigid sequence: each agent only sees what the previous agent handed it. No backtracking.
- If the obituary names a new relative the VSR never searched for, that name can't be fed back to SkipGenie.
- VSR decides vital_status before the obituary is found — if the obit would have confirmed it, that confirmation comes too late to help.
- The Vital Status Gate discards `unknown` people permanently. Obituary research might have resolved them.
- Person Compiler loads from DB but depends entirely on what prior agents chose to write — garbage in, garbage out.
- Surname Crosser fires unconditionally even when the obituary already named all children.
- Multiple separate JSON parse nodes break the chain if any upstream agent outputs unexpected format.
- Title Attorney and Person Compiler are separate agents with separate DB reads, creating a 2-agent redundancy for what is logically one synthesis step.

---

## Workflow 3 — Family Assembly

**Trigger:** After worker queue empties.

**Purpose:** Build the full heir family tree across all researched persons. Apply intestate
succession rules. Queue any remaining cascade persons not caught by the worker loop.

### Sequence

| Step | Node | What it does |
|------|------|-------------|
| 1 | `FA Webhook` | Receives trigger from worker. |
| 2 | `Family Assembler` (Agent) | Reads all persons + ancestry records. Maps full family tree. |
| 2a | → `Load Family Dataset` | All persons for this session with research results. |
| 2b | → `Load Obituary Texts` | All obituary texts for cross-referencing. |
| 2c | → `Ancestry Search (FA)` | Additional ancestry searches for unresolved persons. |
| 2d | → `Load Ancestry Records (FA)` | All ancestry records for the session. |
| 2e | → `Load Voter Records (FA)` | All voter records for the session. |
| 3 | `Parse Family Tree` | JS code node. Extracts family structure. |
| 4 | `Intestate Expert` (Agent) | Applies NC Ch. 29 intestate succession to the full tree. |
| 4a | → `Filter Cascade Persons` | Filters persons that need cascade research. |
| 5 | `Parse Intestate Output` | JS code node. Extracts cascade list. |
| 6 | `More Cascade?` | If new persons to research → FA Queue Cascade → FA Trigger Worker. |
| 7 | `Genealogist` (Agent) | Final genealogy synthesis. Writes family tree to DB. |
| 7a | → `Write Family Tree DB` | Persists final family tree. |

---

## Total Agent Count: 10 agents across 3 workflows

| Workflow | Agents |
|----------|--------|
| Root Research | Root Owner Research, Branch Planner |
| Worker Loop | SG Analyzer, Vital Status Researcher, Obituary Deep Diver, Surname Crosser, Title Attorney, Person Compiler, Branch Decision |
| Family Assembly | Family Assembler, Intestate Expert, Genealogist |

---

## Data Flow Diagram (simplified)

```
Webhook
  └─ Create Session
       └─ Root Owner Research ──────────────────────────┐
            (SkipGenie, Ancestry, Court, Voter, Obit)   │
                                                         ↓
                                                  Write Root Person
                                                         │
                                                         ↓
                                                  Branch Planner
                                               (reads DB, seeds queue)
                                                         │
                                                         ↓
                                              ┌─ Worker Webhook ─────────┐
                                              │                          │
                                              ↓                    (loop back)
                                       Claim Next Person
                                              │
                                    ┌─────────┴──────────┐
                              (claimed)             (empty → FA)
                                    │
                             Parse Attempts
                                    │
                              SkipGenie x5
                                    │
                              SG Analyzer
                                    │
                            Upsert Person SG
                                    │
                         Vital Status Researcher
                                    │
                           Vital Status Gate
                          (unknown → discard)
                                    │
                        Obituary Deep Diver
                                    │
                          Surname Crosser
                                    │
                          Title Attorney
                                    │
                         Person Compiler
                                    │
                         Branch Decision
                                    │
                          Mark Person Done
                                    │
                       Self Trigger Worker (loop)
```
