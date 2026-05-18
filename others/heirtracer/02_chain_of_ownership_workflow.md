# Chain of Ownership Workflow — Handoff Context

**File:** `ScraperSystems/others/new architecture/state.json`  
**Nodes:** 49  
**n8n trigger:** Webhook POST  
**Status:** Complete and working

## What It Does

The Chain of Ownership workflow takes a property ID and runs a multi-agent investigation to confirm:
1. The current owner of record is deceased
2. The property has no formal estate transfer (no probate, no deed transfer after death)
3. The property is therefore "heir property" — a lead for TitleMatrix

## Agent Architecture

| Agent | Model | Role |
|-------|-------|------|
| Case Manager | claude-sonnet-4-6 | Orchestrates all sub-agents, tracks loops/objections |
| Property Researcher | claude-haiku-4-5-20251001 | County assessor + deed lookup |
| Title Attorney | claude-sonnet-4-6 | Legal analysis of ownership gaps |
| Conclusion Writer | claude-haiku-4-5-20251001 | Drafts conclusion for Senior Partner |
| Senior Partner | claude-sonnet-4-6 | Final verdict: approved/rejected/needs_more_info |

## Tool Endpoints (all port 8000)

- `GET /investigate/scout` — property lookup by address
- `GET /investigate/assess/{county}/{pin}` — county assessor data
- `GET /investigate/pull-deed` — deed record from ROD
- `GET /investigate/court-search` — NC court probate/estate search
- `POST /investigate/log-trace` — write investigation_trace row
- `POST /investigate/court-pull` — write court_captures row
- `POST /investigate/conclude-write` — write chain_conclusions row
- `POST /investigate/verify-write` — update investigation_sessions

## Output Schema (chain_conclusions row)

```json
{
  "property_id": 1,
  "session_id": 1,
  "verdict": "approved",
  "status": "heir_property_confirmed",
  "stop_reason": "estate_path_unresolved",
  "current_owners": [
    {
      "name": "Lydia Hayes",
      "owner_number": 1,
      "estate_path_unresolved": true,
      "approx_death_year": "1954",
      "last_known_county": "Wake"
    }
  ],
  "loops": 2,
  "objections": []
}
```

## Heir Tracer Trigger Condition

The heir tracer fires when a `chain_conclusions` row has:
- `verdict = "approved"`
- `stop_reason = "estate_path_unresolved"` (or status = "heir_property_confirmed")
- At least one entry in `current_owners` where `estate_path_unresolved = true`

## Neon DB Tables Written By This Workflow

- `properties` — property record
- `appraiser_transfer_history` — assessor data
- `rod_captures` — deed records
- `court_captures` — court/probate records
- `document_extractions` — extracted document data
- `investigation_sessions` — session tracking
- `investigation_trace` — step-by-step trace log
- `investigation_questions` — agent Q&A log
- `incidental_records` — misc findings
- `chain_conclusions` — **final output** (heir tracer reads this)

## Important: What This Workflow Does NOT Do

- Does NOT do SkipGenie lookup
- Does NOT search obituaries or SSDI
- Does NOT calculate heir shares
- Does NOT write to the FPILS/realestate CRM
- Does NOT call port 8001 (SkipGenie API)

All of that is the heir tracer's job (Steps 3–5).
