# Heir Tracing System — Development Phases

---

## Phase 0 — Setup & Prerequisites
**Goal:** Everything is ready before writing a single n8n node.

- [ ] Run `CREATE TABLE heir_traces` in Neon console (SQL is in the plan)
- [ ] Get Brave Search API key (free tier, 2,000 searches/month)
- [ ] Add credentials in n8n: Neon DB, Brave Search API
- [ ] Verify skipgenieapi is running: `GET http://127.0.0.1:8001` → `{"status":"ok"}`
- [ ] Confirm realestate backend URL + auth token (needed for Phase 6)

**Done when:** All credentials exist in n8n, DB table exists, skipgenieapi responds.

---

## Phase 1 — Parallel Load + Estate Analysis (Root Owner)
**Nodes:** Webhook → 3 branches (Postgres, Skip Tracer Root, Verification Root) → Merge → Estate Analyst Root → Code: Parse Heir List

- [ ] Webhook node (POST `/heir-trace/start`)
- [ ] Postgres: Load Context (query chain_conclusions + investigation_sessions Phase D)
- [ ] Skip Tracer Agent: Root Owner + SkipGenie HTTP tool
- [ ] Verification Agent: Root Owner + Brave Search tool
- [ ] Merge: Phase 1
- [ ] Estate Analyst Agent: Root Owner (always Chapter 29 — `estate_path_unresolved` confirmed)
- [ ] Code: Parse Heir List (output: array of `{name, relationship, share_pct}`)

**Test:** Send Lydia Hayes payload → get structured heir list (Dennis, Sharon) with shares.

---

## Phase 2 — Level-1 Heir Tracing (Parallel)
**Nodes:** Split In Batches → Skip Tracer Per Heir + Verification Per Heir → Code: Route + Accumulate → Merge

- [ ] Split In Batches: Level-1 Heirs
- [ ] Skip Tracer Agent: Per Heir + SkipGenie HTTP tool
- [ ] Verification Agent: Per Heir + Brave Search tool
- [ ] Code: Route + Accumulate (separate living vs deceased into queues)
- [ ] Merge: Level-1 Complete

**Test:** Dennis and Sharon traced in parallel → Dennis alive (confirmed), Sharon deceased (confirmed). Correct queues populated.

---

## Phase 3 — Cascade Loop (Recursive Deceased Heirs)
**Nodes:** IF Any Deceased → Split In Batches Cascade → 4 agents → Code: Route → IF Still Deceased (loop-back or accumulate)

- [ ] IF: Any Deceased in Queue?
- [ ] Split In Batches: Cascade (with DONE output wiring)
- [ ] Court Research Agent + Court Search HTTP + Register of Actions HTTP tools
- [ ] Estate Analyst Agent: Cascade (will vs Chapter 29 branching)
- [ ] Skip Tracer Agent: Cascade + SkipGenie HTTP tool
- [ ] Verification Agent: Cascade + Brave Search tool
- [ ] Code: Route Cascade Results
- [ ] IF: Heir Still Deceased? → TRUE loops back to Split, FALSE → Code: Accumulate Living
- [ ] Circular reference guard in Code node (check ancestor_names)

**Test:** Sharon Hayes (deceased) cascades → her heirs found → living heirs accumulate with correct fractional shares.

---

## Phase 4 — Compile + Write Output
**Nodes:** Code: Merge All → Heir Tree Compiler → Code: Parse Output → Postgres: Write → Respond

- [ ] Code: Merge All Results (combine living from Phase 2 + Phase 3 cascade)
- [ ] Heir Tree Compiler Agent (builds final `heir_tree` JSON with gap flags)
- [ ] Code: Parse Output (validate structure, set `status = complete` or `manual_review`)
- [ ] Postgres: Write heir_traces
- [ ] Respond to Webhook

**Test:** Full end-to-end — Lydia Hayes → structured heir tree returned with phones, addresses, shares, gaps list, credits used.

---

## Phase 5 — FPILS Sync
**Nodes:** Code: Build FPILS Payload → FPILS Sync Agent (5 HTTP tools) → Postgres: Mark synced

- [ ] Confirm realestate backend is accessible + get auth token
- [ ] Code: Build FPILS Payload (map heir_tree fields to FPILS schema)
- [ ] FPILS Sync Agent with 5 HTTP tools:
  - GET property-people (supersede check)
  - POST /facts (date_of_death, will_exists, probate_case_filed, etc.)
  - POST /facts/{id}/evidence (attach obituary URLs)
  - POST /property-people/heirs (atomic heir creation)
  - POST /computations/recompute
- [ ] Postgres: Mark `fpils_synced_at`

**Test:** Heir tree synced → property-people heirs appear in FPILS → recompute triggered.

---

## Phase 6 — SSDI Scraper (Tier 2 Verification)
**Goal:** Fallback when Brave Search obituary finds nothing.

- [ ] Build `ssdiscraper` Python handler (port 8003, FamilySearch SSDI API — same pattern as skipgenieapi)
- [ ] Test: `POST http://127.0.0.1:8003` with name + state → returns `{is_deceased, dod, ssdi_number}`
- [ ] Add SSDI HTTP tool to all 3 Verification Agents as Tier 2 fallback
- [ ] Update Verification Agent system prompt: obituary first → SSDI fallback

**Test:** Heir with no obituary → SSDI confirms deceased → `verification_source = ssdi`.

---

## Phase 7 — Production Hardening
**Goal:** Safe to run on VPS with real properties.

- [ ] IPRoyal residential proxy configured in skipgenieapi (VPS IP is blacklisted)
- [ ] Daily credits cap (200/day) — Code node checks `credits_remaining` and halts gracefully
- [ ] Queue mode — prevent two workflows running simultaneously (one property at a time)
- [ ] `manual_review` status path — heirs with no SkipGenie match or verification conflict get flagged, not crashed
- [ ] Gaps list surfaced clearly in webhook response so James can see what needs manual follow-up

---

## Summary

| Phase | Focus | Blocker |
|---|---|---|
| 0 | Setup | Brave Search key, realestate URL |
| 1 | Root load + estate analysis | — |
| 2 | Level-1 parallel tracing | Phase 1 done |
| 3 | Cascade loop | Phase 2 done + court search working |
| 4 | Compile + write to DB | Phase 3 done |
| 5 | FPILS sync | Phase 4 done + realestate backend accessible |
| 6 | SSDI scraper | Phase 4 done |
| 7 | Production hardening | Phases 1–6 tested |

**Recommended build order:** Phase 0 → 1 → 2 → 4 (skip cascade, test with all-living heirs first) → 3 → 5 → 6 → 7
