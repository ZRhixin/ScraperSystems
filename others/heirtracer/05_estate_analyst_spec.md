# Estate Analyst Agent — Implementation Spec

**Source:** `ScraperSystems/others/skipgenie/guide_estate_analyst.md` (James' document)  
**Role:** Legal-reasoning brain of the heir tracer. Stateless between runs. Multi-run by design.

---

## Core Design Principle

The agent is **stateless between invocations**. It reads the complete current state from the DB at the start of every run, applies NC Ch. 29, writes conclusions + dispatches back to DB. Every run is a new `estate_analyst_runs` row.

This means:
- Crashes are recoverable — restart from last DB state
- Sub-agents can complete in parallel; agent re-runs on each completion
- Full audit trail for legal review
- Agent can be upgraded without state migration

---

## Cascade Loop

```
1. Trigger: property with deceased owner (estate_path_unresolved = true)
2. Initial run: dispatch step=10 (SkipGenie) + step=20 (obituary) for root decedent
3. Estate Analyst runs → identifies heirs → inserts property_people rows + research_events
4. Sub-agents run in parallel → write findings → insert step=99 (re-analyze) events
5. n8n sees step=99 → re-invokes Estate Analyst
6. Estate Analyst reads new state → updates conclusions → may dispatch more sub-agents
7. If heir is deceased → dispatch step=10+20 for THAT heir (cascade)
8. Cascade continues until all branches = living / escheat / human_review
9. Final: Heir Tree Compiler assembles output → heir_traces row
```

---

## Sub-Agent Step Taxonomy

| step | Name | Routes To | Payload |
|------|------|-----------|---------|
| 10 | `skip_genie_lookup` | Skip Tracer Agent | person_id, full_name, last_known_state, dob_estimate |
| 20 | `obituary_search` | Verification Agent | person_id, full_name, dod_estimate_window, known_relatives |
| 21 | `obituary_search_via_spouse` | Verification Agent | person_id, spouse_name, spouse_dod_window |
| 30 | `ssdi_lookup` | Verification Agent | person_id, full_name, dob, last_known_state |
| 40 | `court_probate_search` | Court Research Agent | person_id, full_name, county, state, dod_window |
| 41 | `will_retrieval` | Court Research Agent | person_id, probate_case_number, court_county |
| 50 | `marital_status_research` | Verification Agent | person_id, dod |
| 51 | `paternity_research` | Court Research Agent | person_id, putative_father_name |
| 52 | `adoption_research` | Court Research Agent | person_id, suspected_jurisdiction |
| 60 | `kinship_degree_compute` | Deterministic function (no LLM) | person_id, decedent_person_id |
| 70 | `survival_120hr_evaluation` | Deterministic function | person_id, decedent_person_id |
| 80 | `slayer_check` | Verification Agent | person_id, decedent_person_id |
| **99** | `estate_analyst_reanalyze` | **Estate Analyst itself** | property_id, decedent_person_id, triggering_event_id, reason |

**Sub-agent completion protocol:**
1. Write findings to appropriate DB fields
2. Update `research_events` row: status='completed'
3. Insert NEW `research_events` row with step=99 (triggers Estate Analyst re-run)
4. If failed: still insert step=99 so Estate Analyst can handle the failure

---

## DB Tables Required in FPILS DB

### `estate_analyst_runs` (NEW — must be created via migration)

```sql
CREATE TABLE estate_analyst_runs (
    id SERIAL PRIMARY KEY,
    property_id INTEGER NOT NULL REFERENCES properties(id),
    decedent_person_id INTEGER NOT NULL REFERENCES property_people(id),
    run_number INTEGER NOT NULL,
    triggered_by VARCHAR(50) NOT NULL,          -- 'bootstrap' | 'step_99' | 'manual'
    triggering_event_id UUID REFERENCES research_events(id),

    facts_snapshot JSONB NOT NULL,              -- snapshot of facts at run time
    relationships_snapshot JSONB NOT NULL,

    determination_status VARCHAR(30) NOT NULL
        CHECK (determination_status IN (
            'complete', 'blocked_pending_facts', 'partial',
            'escalate_human', 'escheat', 'error')),

    conclusions JSONB NOT NULL,                 -- per §4.2 schema
    gaps JSONB NOT NULL DEFAULT '[]',           -- per §4.3 schema
    dispatched_tasks JSONB NOT NULL DEFAULT '[]', -- per §4.4 schema
    citations JSONB NOT NULL DEFAULT '[]',      -- per §4.5 schema

    confidence VARCHAR(20) NOT NULL
        CHECK (confidence IN ('high', 'medium', 'low', 'unverified')),
    confidence_rationale TEXT,
    requires_human_review BOOLEAN NOT NULL DEFAULT false,
    human_review_reason TEXT,

    model_version VARCHAR(50),
    prompt_version VARCHAR(20),
    tokens_used INTEGER,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (property_id, decedent_person_id, run_number)
);
```

### `v_estate_analyst_state` (NEW VIEW)

Gives the Estate Analyst its complete working state in one read. Joins `property_people`, `property_people_relationships`, `estate_analyst_runs`, and `research_events`.

Full DDL in `guide_estate_analyst.md` Section 3.2.

---

## Agent Output Schema (what the LLM must return)

```json
{
  "determination_status": "complete|blocked_pending_facts|partial|escalate_human|escheat|error",
  "conclusions": { "decedent": {...}, "spousal_analysis": {...}, "heirs": [...], "totals": {...} },
  "gaps": [{ "gap_id": "uuid", "subject_person_id": 123, "fact_needed": "...", "priority": "blocking" }],
  "dispatched_tasks": [{ "research_event_id": "uuid", "step": 20, "subject_person_id": 123 }],
  "citations": [{ "section": "29-14(a)(2)", "applied_to": "spouse_share", "conclusion": "..." }],
  "confidence": "high|medium|low|unverified",
  "confidence_rationale": "...",
  "requires_human_review": false,
  "human_review_reason": null,
  "person_updates": [{ "person_id": 123, "field_path": "research_metadata.marital_status_at_death.value", "new_value": "married" }],
  "relationships_to_create": [{ "person_id": 123, "related_to_person_id": 456, "relationship_type": "child_of" }],
  "new_persons_to_create": [{ "temp_id": "temp_1", "full_name": "...", "person_type": "heir", "is_deceased": false }]
}
```

---

## Estate Analyst System Prompt (Summary)

The full prompt is in `guide_estate_analyst.md` Section 6. Key directives:

1. **Confirm intestacy applies first** — testate → stop or partial intestacy
2. **Pre-1960 death** → escalate_human (Ch. 29 not applicable)
3. **5 required facts** before distribution: DOD, marital status at death, estate filed?, will or intestate?, which family alive at death?
4. **Apply GS 29-14** (spouse share) then **GS 29-15** (priority order)
5. **Every heir must be tagged** with one of: living_confirmed, living_unverified, deceased_resolved, deceased_cascading, predeceased_no_descendants, disqualified, renounced, escheat_branch
6. **Shares must sum to 1.0** (100%)
7. **Every conclusion must cite a specific GS section**
8. **Output ONLY valid JSON** — no markdown, no text outside JSON

---

## Worked Example: Lydia Hayes

Lydia Hayes died 1954 → **Pre-1960 death** → determination_status = "escalate_human" with law_applicability_warning. If DOD were post-1960 with 2 children, no spouse: each child gets 1/2 (GS 29-15 priority class 1, GS 29-16(a)(1)).

---

## Human Review Triggers

- Death before Jan 1, 1960 (Ch. 29 not applicable)
- Partial intestacy (will + intestate residue)
- Paternity dispute unresolvable
- Renunciation with unknown scope
- 3+ cascades deep with unresolvable gaps
- Conflicting evidence on survival within 120 hours
- Any heir would escape to 5+ degree collateral kin (borderline escheat)
