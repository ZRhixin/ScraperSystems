Got it. Let me build this as a proper handoff doc — everything a developer needs to implement the Estate Analyst end-to-end without coming back to ask questions. Reading the docx skill first since this is a substantial deliverable.Tooling is still down so I'll deliver this inline. It's long because it has to be — a developer doc needs DDL, JSONB contracts, the prompt, sub-agent contracts, n8n logic, and worked examples. Copy this into a `.md` file in your repo as `docs/estate-analyst-spec.md` or similar. When tools are back I can also produce a Word version.

---

# Estate Analyst Agent — Implementation Specification

**System:** TitleMatrix / FPILS Heir Tracing
**Component:** Estate Analyst Agent (NC Chapter 29)
**Version:** 1.0 (Initial implementation)
**Audience:** Backend developer + n8n workflow developer
**Database:** `heirmatrix_db` (PostgreSQL)
**State Coverage:** North Carolina only (subsequent states will follow the same architecture with state-specific legal modules)

---

## Table of Contents

1. System Overview
2. Architecture & Data Flow
3. Database Schema Additions
4. JSONB Field Contracts
5. Sub-Agent Step Taxonomy
6. The Estate Analyst Prompt
7. n8n Workflow Implementation
8. Worked Example: End-to-End Trace
9. Edge Cases & Human Review Triggers
10. Testing & Validation
11. Deployment Checklist

---

## 1. System Overview

### Purpose

When a property owner dies without a recorded will or open estate case, the property's ownership passes by intestate succession to heirs. Identifying those heirs requires:

1. Establishing facts about the decedent (date of death, marital status, surviving relatives)
2. Applying the relevant state's intestate succession statute to those facts
3. Recursively repeating the process for any heir who has also died, until every branch ends at a living person
4. Assigning each living heir a fractional ownership share

The **Estate Analyst Agent** is the legal-reasoning brain of this system. It does not search for facts — that's done by sub-agents. It does not orchestrate workflows — that's done by n8n. Its sole job is to reason over the facts that exist at any given moment, determine what conclusions can be drawn under NC Chapter 29, and identify what additional facts are needed to make further conclusions.

### Key design principle

The agent is **stateless between invocations**. Every fact, every conclusion, every gap, every dispatched task lives in the database. The agent reads its complete working state from the database at the start of every run and writes its complete output back at the end. This means:

- Workflow crashes are recoverable — restart from the last database state
- Multiple sub-agents can complete in parallel and the agent re-runs whenever new facts arrive
- Full audit trail for legal review (every conclusion ties to a Ch. 29 citation)
- The agent can be replaced or upgraded without state migration

### What the agent is NOT responsible for

- Doing web searches (sub-agents do this)
- Calling APIs (sub-agents and n8n do this)
- Deciding which sub-agent to invoke (n8n routes based on `research_events.step`)
- Final share computation displayed to the user (FPILS computation engine handles this)
- Compiling the final heir tree (Heir Tree Compiler does this in Phase 5)

---

## 2. Architecture & Data Flow

### Component map

```
┌─────────────────────────────────────────────────────────────┐
│                         n8n Workflow                        │
│  (Orchestrator — polls research_events, routes to agents)   │
└────┬────────────┬────────────┬────────────┬─────────────────┘
     │            │            │            │
     ▼            ▼            ▼            ▼
┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│  Skip   │ │Verifica- │ │  Court   │ │   ESTATE     │
│ Tracer  │ │  tion    │ │ Research │ │   ANALYST    │
│ Agent   │ │  Agent   │ │  Agent   │ │   AGENT      │
└────┬────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘
     │           │            │              │
     │ Each writes findings to DB │          │
     │           │            │              │
     ▼           ▼            ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│                   PostgreSQL Database                       │
│  property_people, property_people_relationships,            │
│  research_events, research_documents, property_cases,       │
│  estate_analyst_runs (NEW)                                  │
└─────────────────────────────────────────────────────────────┘
```

### The cascade loop

1. **Trigger:** Workflow fires for a property with a deceased owner.
2. **Initial fact gathering:** n8n dispatches Skip Tracer + obituary search for the root decedent. They write findings to `property_people` and `research_metadata`.
3. **First Estate Analyst run:** Agent reads state, applies Ch. 29 to known facts. If it has enough facts to identify heirs, it inserts `property_people` rows for each heir (or links to existing ones) and inserts `research_events` rows requesting verification of each heir. If it doesn't have enough facts, it lists gaps in `estate_analyst_runs.gaps` and dispatches sub-agents to fill them.
4. **Sub-agents run in parallel.** Each one writes its findings to the DB and inserts a `research_events` row with `step=99` ("re-analyze") when done.
5. **Re-invocation:** n8n sees the `step=99` event and invokes the Estate Analyst again. The agent reads the new state, updates conclusions, may dispatch more sub-agents.
6. **Cascade:** When the agent finds a deceased heir, it inserts a research event to investigate that person as a new sub-decedent. The cascade continues until every branch resolves to a living person, an escheat determination, or a human review flag.
7. **Final compilation:** Once the agent's most recent run for the root decedent has `determination_status='complete'` and all sub-decedents are resolved, the Heir Tree Compiler assembles the final output.

### Data flow per agent run

```
INPUT (read by agent):
  - estate_analyst_runs (latest run for this decedent + all prior runs)
  - v_estate_analyst_state (single view giving complete person + relationships + events)
  - property_cases (probate filings)
  - research_documents (evidence)

PROCESSING (in agent prompt):
  1. Identify decedent and all known relatives
  2. Apply NC Ch. 29 decision tree to known facts
  3. Identify what's known vs unknown
  4. Determine which gaps block conclusions
  5. Generate dispatch tasks for sub-agents to fill blocking gaps
  6. Compute provisional shares for whatever can be determined
  7. Cite each conclusion to a specific Ch. 29 section

OUTPUT (written by agent):
  - INSERT into estate_analyst_runs (the new run record)
  - UPDATE property_people.research_metadata (new facts the agent inferred)
  - UPDATE property_people.ownership_percentage (when share is final)
  - INSERT property_people_relationships (when agent infers relationships)
  - INSERT research_events (dispatch tasks, status='pending')
```

---

## 3. Database Schema Additions

All additions are **non-breaking**. No existing columns altered, no triggers modified.

### 3.1 New table: `estate_analyst_runs`

```sql
CREATE SEQUENCE estate_analyst_runs_id_seq;

CREATE TABLE estate_analyst_runs (
    id INTEGER NOT NULL DEFAULT nextval('estate_analyst_runs_id_seq'::regclass),
    property_id INTEGER NOT NULL,
    decedent_person_id INTEGER NOT NULL,
    run_number INTEGER NOT NULL,
    triggered_by VARCHAR(50) NOT NULL,
    triggering_event_id UUID,

    facts_snapshot JSONB NOT NULL,
    relationships_snapshot JSONB NOT NULL,

    determination_status VARCHAR(30) NOT NULL,
    conclusions JSONB NOT NULL,
    gaps JSONB NOT NULL DEFAULT '[]'::jsonb,
    dispatched_tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,

    confidence VARCHAR(20) NOT NULL,
    confidence_rationale TEXT,
    requires_human_review BOOLEAN NOT NULL DEFAULT false,
    human_review_reason TEXT,

    model_version VARCHAR(50),
    prompt_version VARCHAR(20),
    tokens_used INTEGER,
    duration_ms INTEGER,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),

    PRIMARY KEY (id),

    CONSTRAINT estate_analyst_runs_property_id_fkey
        FOREIGN KEY (property_id) REFERENCES properties(id),
    CONSTRAINT estate_analyst_runs_decedent_person_id_fkey
        FOREIGN KEY (decedent_person_id) REFERENCES property_people(id),
    CONSTRAINT estate_analyst_runs_triggering_event_id_fkey
        FOREIGN KEY (triggering_event_id) REFERENCES research_events(id),
    CONSTRAINT estate_analyst_runs_unique_run
        UNIQUE (property_id, decedent_person_id, run_number),
    CONSTRAINT estate_analyst_runs_status_check
        CHECK (determination_status IN
            ('complete', 'blocked_pending_facts', 'partial', 'escalate_human', 'escheat', 'error')),
    CONSTRAINT estate_analyst_runs_confidence_check
        CHECK (confidence IN ('high', 'medium', 'low', 'unverified'))
);

CREATE INDEX idx_estate_analyst_runs_property ON estate_analyst_runs(property_id);
CREATE INDEX idx_estate_analyst_runs_decedent ON estate_analyst_runs(decedent_person_id);
CREATE INDEX idx_estate_analyst_runs_status ON estate_analyst_runs(determination_status);
CREATE INDEX idx_estate_analyst_runs_review ON estate_analyst_runs(requires_human_review)
    WHERE requires_human_review = true;
CREATE INDEX idx_estate_analyst_runs_created ON estate_analyst_runs(created_at DESC);
CREATE INDEX idx_estate_analyst_runs_latest ON estate_analyst_runs(property_id, decedent_person_id, run_number DESC);
```

### 3.2 New helper view: `v_estate_analyst_state`

```sql
CREATE OR REPLACE VIEW v_estate_analyst_state AS
SELECT
    pp.property_id,
    pp.id AS person_id,
    pp.full_name,
    pp.first_name,
    pp.middle_name,
    pp.last_name,
    pp.is_deceased,
    pp.date_of_birth,
    pp.date_of_death,
    pp.research_status,
    pp.research_metadata,
    pp.ownership_percentage,
    pp.probate_status,
    pp.estate_status,
    pp.probate_case_number,
    pp.court_county,
    pp.person_type,

    (SELECT jsonb_agg(jsonb_build_object(
        'related_person_id', ppr.related_to_person_id,
        'relationship_type', ppr.relationship_type,
        'family_relationship', ppr.family_relationship,
        'detail', ppr.relationship_detail
    )) FROM property_people_relationships ppr WHERE ppr.person_id = pp.id) AS relationships_out,

    (SELECT jsonb_agg(jsonb_build_object(
        'related_person_id', ppr.person_id,
        'relationship_type', ppr.relationship_type,
        'family_relationship', ppr.family_relationship
    )) FROM property_people_relationships ppr WHERE ppr.related_to_person_id = pp.id) AS relationships_in,

    (SELECT row_to_json(ear.*) FROM estate_analyst_runs ear
        WHERE ear.decedent_person_id = pp.id
        ORDER BY ear.run_number DESC LIMIT 1) AS latest_run,

    (SELECT jsonb_agg(jsonb_build_object(
        'event_id', re.id,
        'step', re.step,
        'status', re.status,
        'payload', re.payload,
        'created_at', re.created_at,
        'updated_at', re.updated_at
    ) ORDER BY re.created_at DESC)
        FROM research_events re
        WHERE re.person_id = pp.id
            AND re.status IN ('pending', 'completed', 'failed')) AS events

FROM property_people pp
WHERE pp.deleted_at IS NULL;
```

### 3.3 No other DDL changes required

- `property_people` — additions go inside existing `research_metadata` JSONB column
- `property_people_relationships` — uses existing `family_relationship` field for half/whole blood
- `research_events` — uses existing `step` SMALLINT with the taxonomy in §5
- `research_documents`, `property_cases`, `research_notes` — unchanged

---

## 4. JSONB Field Contracts

These are the contracts between the Estate Analyst, the sub-agents, and the FPILS engine. Implement each as a TypeScript interface or JSON Schema validator in the application layer to enforce shape at write time.

### 4.1 `property_people.research_metadata` schema

This object lives on every `property_people` row that the heir tracing system has touched. Sub-agents write findings into specific sub-fields. The Estate Analyst reads the entire object on every run.

```json
{
  "marital_status_at_death": {
    "value": "married",
    "_allowed": ["married", "divorced", "widowed", "single", "common_law", "unknown"],
    "spouse_person_id": null,
    "marriage_date": null,
    "marriage_ended_date": null,
    "marriage_validity": {
      "type": "ceremonial",
      "_allowed_type": ["ceremonial", "common_law", "unknown"],
      "jurisdiction_of_formation": null,
      "recognized_in_nc": true
    },
    "equitable_distribution_award": {
      "applicable": false,
      "awarded_to_spouse_amount": null,
      "g_s_50_20_status": null
    },
    "source": null,
    "evidence_url": null,
    "confidence": "unverified",
    "_allowed_confidence": ["verified", "probable", "unverified"]
  },

  "survival_evaluation": {
    "evaluated_against_decedent_id": null,
    "survived_decedent": null,
    "survived_120_hours": null,
    "days_between_deaths": null,
    "simultaneous_death_presumption": {
      "applies": false,
      "basis": null
    },
    "basis": null,
    "source_evidence_id": null,
    "confidence": "unverified"
  },

  "disqualifications": [
    {
      "type": "slayer",
      "_allowed_types": ["slayer", "renunciation", "advancement_full_satisfaction", "alien_pre_2011", "other"],
      "established": false,
      "ch_31_basis": null,
      "renunciation_details": {
        "scope": null,
        "_allowed_scope": ["full", "partial", "specific_asset"],
        "filed_date": null,
        "filing_court": null,
        "renounced_portion_description": null
      },
      "source": null,
      "confidence": "unverified"
    }
  ],

  "adoption": {
    "is_adopted": false,
    "adopted_by_person_ids": [],
    "natural_parents_person_ids": [],
    "stepparent_adoption_exception": false,
    "natural_parent_married_adoptive_parent": false,
    "adoption_jurisdiction": null,
    "source": null,
    "confidence": "unverified"
  },

  "legitimation": {
    "applicable": false,
    "legitimated": null,
    "statute_basis": null,
    "_allowed_basis": ["g_s_49-10", "g_s_49-12", "other_jurisdiction"],
    "legitimation_date": null,
    "source": null,
    "confidence": "unverified"
  },

  "paternity": {
    "born_out_of_wedlock": false,
    "father_established": null,
    "establishment_method": null,
    "_allowed_methods": [
      "adjudication_49-1_to_49-9",
      "adjudication_49-14_to_49-16",
      "written_acknowledgment_52-10b",
      "dna_father_died_within_1yr",
      "probated_will_acknowledgment",
      "not_established"
    ],
    "father_person_id": null,
    "can_inherit_upward_from_father": false,
    "six_month_notice_filed": null,
    "source": null,
    "confidence": "unverified"
  },

  "testacy": {
    "had_will": null,
    "will_admitted_to_probate": null,
    "disposition_type": null,
    "_allowed_disposition": ["fully_testate", "partially_testate", "fully_intestate", "unknown"],
    "intestate_residue_exists": null,
    "intestate_residue_description": null,
    "probate_case_id": null,
    "source": null,
    "confidence": "unverified"
  },

  "spousal_election": {
    "applicable": false,
    "election_made": null,
    "election_type": null,
    "_allowed_types": ["one_third_life_estate", "dwelling_life_estate", "combined", "waived"],
    "household_furnishings_elected": false,
    "dwelling_plus_supplemental_real_estate": false,
    "filed_date": null,
    "deadline_date": null,
    "deadline_expired": null,
    "waiver_basis": null,
    "_allowed_waiver": [
      "joint_conveyance",
      "express_written_waiver",
      "g_s_52-10",
      "g_s_39-13.3",
      "g_s_41-63",
      "partition_pre_death",
      "not_legally_entitled"
    ]
  },

  "posthumous_birth": {
    "applicable": false,
    "born_within_10_lunar_months": null,
    "birth_date": null,
    "source": null
  },

  "advancements": [
    {
      "advancee_person_id": null,
      "transfer_date": null,
      "value_at_possession": null,
      "value_at_death": null,
      "valuation_used": null,
      "_allowed_valuation": ["possession_date", "death_date", "written_designation"],
      "designated_in_writing": false,
      "exceeds_intestate_share": null,
      "excludes_from_distribution": null,
      "inventory_refused": false,
      "written_release_signed": false,
      "advancee_predeceased": false,
      "passes_to_advancee_descendants": false,
      "descendant_recipient_ids": [],
      "source": null,
      "confidence": "unverified"
    }
  ],

  "kinship_degree_to_decedent": {
    "decedent_person_id": null,
    "degree": null,
    "computed_per_g_s_104A_1": false,
    "within_5_degrees": null
  },

  "decedent_estate_interests": [
    {
      "interest_type": "fee_simple",
      "_allowed_types": ["fee_simple", "life_estate_pur_autre_vie", "remainder", "reversion", "executory_interest", "right_of_entry", "possibility_of_reverter"],
      "underlying_property_description": null,
      "conditions": null
    }
  ],

  "estate_analyst_internal": {
    "last_run_id": null,
    "last_run_at": null,
    "branch_status": "unresolved",
    "_allowed_branch": ["unresolved", "resolved_living", "resolved_deceased_cascading", "resolved_deceased_terminal", "escheat", "human_review"],
    "cascade_root_decedent_id": null
  }
}
```

### 4.2 `estate_analyst_runs.conclusions` schema

```json
{
  "decedent": {
    "person_id": 12345,
    "full_name": "Lydia Hayes",
    "date_of_death": "1954-03-12",
    "intestacy_status": "fully_intestate",
    "applicable_law": "NC General Statutes Chapter 29",
    "law_version_at_dod": "Pre-1959 NC inheritance law (Chapter 29 effective 1960; for deaths before 1960, common law and prior statutes apply — escalate to human review)",
    "law_applicability_warning": null
  },
  "spousal_analysis": {
    "spouse_at_death": null,
    "spouse_person_id": null,
    "spouse_survived_120_hours": null,
    "spouse_share_real_fraction": null,
    "spouse_share_real_decimal": null,
    "spouse_share_personal_calculation": {
      "net_personal_property_value": null,
      "personal_property_floor_applied": null,
      "_allowed_floors": [60000, 100000, null],
      "share_decimal": null,
      "share_description": null
    },
    "elective_life_estate_eligible": false,
    "elective_life_estate_filed": false,
    "equitable_distribution_clawback_applied": false
  },
  "heirs": [
    {
      "person_id": 12346,
      "full_name": "Dennis Hayes",
      "relationship_path": "child",
      "share_fraction": "1/2",
      "share_decimal": 0.5,
      "share_basis": "real_property",
      "_allowed_basis": ["real_property", "personal_property", "both"],
      "statutory_basis": "29-15(2) + 29-16(a)(1)",
      "status": "living_confirmed",
      "_allowed_status": [
        "living_confirmed", "living_unverified",
        "deceased_resolved", "deceased_cascading", "deceased_unverified",
        "predeceased_no_descendants", "disqualified", "renounced", "escheat_branch"
      ],
      "branch_status": "resolved",
      "_allowed_branch_status": ["resolved", "cascading", "blocked", "human_review"],
      "cascade_to_run_id": null,
      "advancement_adjustment": null
    }
  ],
  "collateral_distribution": {
    "applicable": false,
    "paternal_branch_share": null,
    "maternal_branch_share": null,
    "crossover_invoked": false,
    "crossover_reason": null,
    "five_degree_analysis": {
      "any_within_5_degrees": null,
      "escheat_backstop_invoked": false,
      "expanded_search_performed": false
    }
  },
  "totals": {
    "real_property_total": 1.0,
    "personal_property_total": null,
    "sums_to_100_percent": true,
    "discrepancy_explanation": null
  }
}
```

### 4.3 `estate_analyst_runs.gaps` schema

```json
[
  {
    "gap_id": "uuid-v4",
    "subject_person_id": 12347,
    "subject_name": "Sharon Hayes",
    "fact_needed": "date_of_death",
    "_allowed_facts": [
      "date_of_death", "date_of_birth", "marital_status_at_death",
      "spouse_identity", "children_identity", "parents_identity",
      "siblings_identity", "testacy_status", "will_disposition",
      "adoption_status", "paternity_establishment", "renunciation_status",
      "advancement_history", "120_hour_survival", "kinship_degree",
      "obituary_text", "probate_case_records"
    ],
    "why_needed": "Required to determine which of Sharon's children were alive at her death per 29-16(a)(2)",
    "blocks_conclusion": "share_distribution_below_sharon",
    "suggested_sources": ["obituary", "ssdi", "death_certificate"],
    "priority": "blocking",
    "_allowed_priority": ["blocking", "important", "nice_to_have"]
  }
]
```

### 4.4 `estate_analyst_runs.dispatched_tasks` schema

This array mirrors the `research_events` rows the agent inserted in this run. Useful for fast lookup without joining.

```json
[
  {
    "research_event_id": "uuid-v4",
    "step": 20,
    "step_name": "obituary_search",
    "subject_person_id": 12347,
    "payload_summary": "Search for Sharon Hayes obituary, NC, deceased between 2005-2020",
    "fills_gap_id": "uuid-of-gap"
  }
]
```

### 4.5 `estate_analyst_runs.citations` schema

```json
[
  {
    "section": "29-14(a)(2)",
    "applied_to": "spouse_real_property_share",
    "conclusion": "Spouse takes 1/3 undivided interest because intestate is survived by 2+ children",
    "facts_supporting": [
      "spouse_alive_at_death=true",
      "spouse_survived_120hrs=true",
      "surviving_descendant_count>=2"
    ]
  },
  {
    "section": "29-3",
    "applied_to": "sibling_classification",
    "conclusion": "Half-blood and whole-blood siblings treated equally for share computation"
  }
]
```

---

## 5. Sub-Agent Step Taxonomy

This is the contract between the Estate Analyst (which inserts dispatch rows) and n8n (which routes them).

| step | Step Name | Routed To | Required Payload Fields | Sub-agent must write to |
|---|---|---|---|---|
| 10 | `skip_genie_lookup` | Skip Tracer | `person_id`, `full_name`, `last_known_state` (optional), `dob_estimate` (optional) | `property_people` (DOB, address, possible_relatives) |
| 20 | `obituary_search` | Verification Agent (Tier 1) | `person_id`, `full_name`, `dod_estimate_window`, `known_relatives` | `property_people.obituary_link`, `obituary_text`, `date_of_death`; `research_metadata.marital_status_at_death`; `research_documents` |
| 21 | `obituary_search_via_spouse` | Verification Agent | `person_id`, `spouse_name`, `spouse_dod_window` | Same as step 20 plus `survival_evaluation` |
| 30 | `ssdi_lookup` | Verification Agent (Tier 2) | `person_id`, `full_name`, `dob`, `last_known_state` | `property_people.date_of_death`, `place_of_death` |
| 40 | `court_probate_search` | Court Research Agent | `person_id`, `full_name`, `county`, `state`, `dod_window` | `property_cases`, `research_metadata.testacy`, `property_people.probate_case_number` |
| 41 | `will_retrieval` | Court Research Agent | `person_id`, `probate_case_number`, `court_county` | `research_documents`, `research_metadata.testacy.disposition_type` |
| 50 | `marital_status_research` | Verification Agent | `person_id`, `dod` | `research_metadata.marital_status_at_death` |
| 51 | `paternity_research` | Court Research Agent | `person_id`, `putative_father_name`, `father_dod` (optional) | `research_metadata.paternity` |
| 52 | `adoption_research` | Court Research Agent | `person_id`, `suspected_jurisdiction` | `research_metadata.adoption` |
| 53 | `legitimation_research` | Court Research Agent | `person_id`, `parent_names` | `research_metadata.legitimation` |
| 54 | `renunciation_research` | Court Research Agent | `person_id`, `decedent_estate_case_number` | `research_metadata.disqualifications[]` (renunciation entry) |
| 55 | `advancement_research` | Court Research Agent | `person_id`, `decedent_person_id` | `research_metadata.advancements[]` |
| 60 | `kinship_degree_compute` | Deterministic function (no LLM) | `person_id`, `decedent_person_id` | `research_metadata.kinship_degree_to_decedent` |
| 70 | `survival_120hr_evaluation` | Deterministic function | `person_id`, `decedent_person_id` | `research_metadata.survival_evaluation` |
| 80 | `slayer_check` | Verification Agent | `person_id`, `decedent_person_id` | `research_metadata.disqualifications[]` (slayer entry) |
| 99 | `estate_analyst_reanalyze` | Estate Analyst itself | `property_id`, `decedent_person_id`, `triggering_event_id`, `reason` | `estate_analyst_runs` |

### Sub-agent completion protocol

When any sub-agent finishes:
1. Write findings to the appropriate database fields per the contract above
2. Update the `research_events` row: `status='completed'`, set `updated_at`
3. Insert a new `research_events` row with `step=99` and payload `{property_id, decedent_person_id, triggering_event_id: <this event's id>, reason: "step_X_completed"}`. This re-invokes the Estate Analyst.

If a sub-agent fails after retries, set `status='failed'` and still insert the `step=99` event. The Estate Analyst will see the failure and decide whether to retry, dispatch an alternative source, or flag for human review.

---

## 6. The Estate Analyst Prompt

This is the system prompt for the LLM. Inject the runtime data described in §6.2 as the user message on each invocation.

### 6.1 System prompt

```
You are the Estate Analyst Agent for the TitleMatrix heir tracing system. You apply North Carolina intestate succession law (NC General Statutes Chapter 29) to determine who inherits a deceased property owner's interest, and you direct sub-agents to gather any additional facts you need.

# YOUR ROLE

You are a legal-reasoning agent. You do NOT search the web, call APIs, or contact people. Other agents do that work. You read the current state of facts from the database, apply NC Chapter 29 to those facts, decide what conclusions can be drawn, identify what facts are still missing, and emit dispatch instructions for sub-agents to fill those gaps.

You run many times across the lifecycle of a single trace. Each run you read the latest state, reason over it, and write conclusions plus next-step dispatches. You are stateless between runs — the database holds all state.

# YOUR OUTPUT FORMAT

You must respond with a single JSON object matching this exact schema:

{
  "determination_status": "complete" | "blocked_pending_facts" | "partial" | "escalate_human" | "escheat" | "error",
  "conclusions": { ... per §4.2 schema ... },
  "gaps": [ ... per §4.3 schema ... ],
  "dispatched_tasks": [ ... per §4.4 schema ... ],
  "citations": [ ... per §4.5 schema ... ],
  "confidence": "high" | "medium" | "low" | "unverified",
  "confidence_rationale": "string explaining the confidence level",
  "requires_human_review": true | false,
  "human_review_reason": "string or null",
  "person_updates": [
    {
      "person_id": <int>,
      "field_path": "research_metadata.marital_status_at_death.value",
      "new_value": "married",
      "reason": "Inferred from obituary text 'survived by his wife Mary'"
    }
  ],
  "relationships_to_create": [
    {
      "person_id": <int>,
      "related_to_person_id": <int>,
      "relationship_type": "child_of" | "spouse_of" | "parent_of" | "sibling_of" | "heir_of",
      "family_relationship": "biological" | "adopted" | "step" | "half_blood_paternal" | "half_blood_maternal",
      "detail": "string or null"
    }
  ],
  "new_persons_to_create": [
    {
      "temp_id": "temp_1",
      "full_name": "John Hayes Jr.",
      "first_name": "John",
      "last_name": "Hayes",
      "person_type": "heir",
      "is_deceased": false,
      "research_metadata": { ... },
      "_relationships_after_creation": [ ... ]
    }
  ]
}

Do not include any text outside this JSON object. Do not include markdown fences.

# THE LAW: NC CHAPTER 29 DECISION TREE

You apply Chapter 29 in this exact order. Every conclusion MUST cite the specific section that drove it.

## Step 1: Confirm intestacy applies (§§29-8, 29-15)

Before applying intestate distribution rules:
- If decedent died testate AND will disposes of all property → STOP, return determination_status="complete" with note that this property passes by will, not intestacy. The will-reading agent (separate system) handles this.
- If decedent died testate but will disposes of only some property (partial intestacy under §29-8) → apply Ch. 29 ONLY to the residue. Set conclusions.decedent.intestacy_status = "partial_intestacy" and document which assets are in the intestate residue.
- If no will exists or will not admitted to probate → fully intestate, proceed.
- If testacy_status is unknown → emit gap with fact_needed="testacy_status" and dispatch step=40 (court_probate_search) and step=41 (will_retrieval if probate_case_number known).

## Step 2: Confirm the law applicable to this decedent

Chapter 29 (the Intestate Succession Act) was enacted in 1959 and took effect for deaths on or after January 1, 1960. For decedents who died BEFORE January 1, 1960, NC's prior inheritance statutes and common law apply, NOT Chapter 29. If date_of_death is before 1960, set requires_human_review=true with reason "Pre-1960 death requires application of prior NC inheritance law, outside this agent's scope" and STOP.

Also account for known amendments:
- §29-14 personal property amounts: $30,000 floor pre-2012; $60,000/$100,000 from 2012-2025 amendments. Apply the version in effect at decedent's date of death.
- §29-19 paternity DNA-after-death rule: added in later amendment. For pre-amendment deaths, only adjudication and written acknowledgment establish paternity for inheritance purposes. (When in doubt about which version applies, set requires_human_review=true.)

## Step 3: Apply the 120-hour survival rule (§29-13(b), Ch. 28A Art. 24)

For every potential heir, check survival_evaluation.survived_120_hours.
- If true → treat as a survivor.
- If false → treat as predeceased. Their share (if any) goes per §§29-15, 29-16 to their lineal descendants if they have any, or back into the pool.
- If unknown AND there's any indication the heir died close in time to the decedent → emit gap, dispatch step=70 (survival_120hr_evaluation).
- If two persons died and order is unknown → simultaneous_death_presumption.applies=true, treat as if each predeceased the other (Ch. 28A standard presumption).

## Step 4: Identify and qualify the surviving spouse (§29-14)

Read marital_status_at_death.value for the decedent.
- "married" + spouse alive at death + survived 120 hrs → spouse takes share per §29-14
- "divorced" / "single" / "widowed" → no spouse share, skip to Step 5
- "common_law" → check marriage_validity.recognized_in_nc. NC does not recognize common-law marriages formed in NC, but recognizes those validly formed in states that do. If formed in NC → no spouse share. If formed elsewhere where valid → treat as married.
- "unknown" → emit gap, dispatch step=50

If equitable_distribution_award.applicable=true → spouse's intestate share is reduced by the ED award amount per §29-14(c). Apply this AFTER computing the base share.

Spouse share by configuration:
| Other survivors | Real property share | Personal property share |
|---|---|---|
| 1 child OR descendants of 1 deceased child | 1/2 | All if ≤$60K, else $60K + 1/2 of balance |
| 2+ children OR mixed descendants of 2+ deceased children | 1/3 | All if ≤$60K, else $60K + 1/3 of balance |
| No descendants but 1+ parents alive | 1/2 | All if ≤$100K, else $100K + 1/2 of balance |
| No descendants, no parents | All | All |

If net_personal_property_value is unknown but you can determine the real property share, set personal_property_share_calculation fields to null and note in conclusions that personal property cannot be calculated until value is established.

## Step 5: Apply spousal life estate election if elected (§29-30)

If spousal_election.election_made=true:
- Override the §29-14 share with a 1/3 life estate in all real estate decedent was seised of during marriage, OR a life estate in the dwelling per §29-30(b).
- Real property the decedent owned during marriage but no longer owned at death is NOT subject to this election if disposed of with spouse's joinder or under exemptions in §29-30(a).
- The election deadline is 12 months from death (or shorter if letters issued). If deadline_expired=true and election_made=false, the election is conclusively waived per §29-30(h).

## Step 6: Distribute the non-spouse share per §29-15

After removing spouse's share (or all of it if no spouse), distribute the remainder in this priority order:

1. **Children + descendants of deceased children** → distribute per §29-16 (per stirpes by representation)
2. **No descendants, but parents alive** → both parents equally; if one parent dead, surviving parent takes all
3. **No descendants, no parents** → siblings and descendants of deceased siblings per §29-16
4. **None of the above** → grandparents and uncles/aunts and their descendants per §29-15(5)
   - 1/2 paternal side, 1/2 maternal side
   - If one side has no qualifying takers, the other side takes all (§29-15(5)(c) and (d))
   - Subject to 5-degree limit under §29-7
5. **No qualifying takers within 5 degrees** → check §29-7 escheat backstop. If still no takers, set determination_status="escheat".

## Step 7: Apply per-stirpes distribution per §29-16

For each generation:
1. Count surviving members of that generation PLUS deceased members who left lineal descendants surviving the decedent.
2. Divide the share equally by that count.
3. Each surviving member takes their share. Each deceased member's share passes to their descendants by recursive application of this rule.

Example: Decedent has 3 children. Child A is alive. Child B is alive. Child C predeceased, leaving 2 children (D and E).
- 3 shares: A gets 1/3, B gets 1/3, C's share (1/3) goes to D and E.
- D and E each get 1/6 (1/3 ÷ 2).

For collateral distributions (siblings, etc.), apply the same rule with the 5-degree limit per §29-16(b)(5) and §29-7.

## Step 8: Apply special class rules

Half-blood vs whole-blood (§29-3): treat as equal. Do NOT distinguish.

Adoption (§29-17):
- Adopted child inherits from adoptive parents and their kin.
- Adopted child does NOT inherit from natural parents or their kin EXCEPT under the stepparent adoption rule (§29-17(e)): if a natural parent is married to the adoptive parent, the child is also considered the natural parent's child for inheritance purposes.
- If adoption.is_adopted=true and the decedent is a natural parent of the child, check adoption.stepparent_adoption_exception. If false, the adopted-out child does NOT inherit from this decedent.
- Conversely, if the decedent is the adoptive parent, the adopted child inherits as a natural child.

Legitimation (§29-18): A child born out of wedlock who has been legitimated under G.S. 49-10 or 49-12 (or other jurisdiction's equivalent) inherits as if born in wedlock — both directions, both parents.

Out-of-wedlock children (§29-19):
- Always inherits from mother (and through mother's kin).
- Inherits from father ONLY if father_established=true via one of the four §29-19(b) methods: (1) adjudication under §§49-1–49-9, (2) adjudication under §§49-14–49-16, (3) written acknowledgment under §52-10(b), or (4) DNA after father's death within 1 year of child's birth.
- Six-month notice requirement: claimant must give written notice of basis to personal representative within 6 months after first publication/posting of general notice to creditors. If six_month_notice_filed=false and probate is open, this may bar the claim.
- Upward inheritance from child to father only available under methods (1), (2), or via acknowledgment in probated will (§29-19(d)). DNA-after-death method does NOT enable upward inheritance.

## Step 9: Apply disqualifications

For each potential heir, check disqualifications[]:
- type=slayer + established=true → person cannot inherit (Ch. 31A). Treat as if predeceased; their share passes per §§29-15, 29-16 to their descendants if any, otherwise back to the pool.
- type=renunciation → renounced share passes as if renouncer predeceased (Ch. 31B). For partial renunciation, only the renounced portion passes; the rest goes to the renouncer.
- type=advancement_full_satisfaction → person excluded from further distribution per §29-25 (advancement equaled or exceeded their share).

## Step 10: Apply advancements (§§29-23–29-29)

Default presumption (§29-24): inter vivos gifts are gifts, NOT advancements, unless shown otherwise. Do NOT treat any transfer as an advancement unless evidence in advancements[] shows it was intended as one.

If an advancement is established:
- Add advancement value back into the hotchpot (the estate value used for share calculation)
- Compute advancee's share including the advancement
- If advancement ≥ share: advancee excluded from further distribution but doesn't refund (§29-25). Mark heir status as "disqualified" with reason advancement_full_satisfaction.
- If advancement < share: advancee gets the difference.
- If advancee predeceased and left descendants who take by intestate succession (§29-27): the advancement counts against those descendants collectively.
- §29-28 inventory refusal: deemed full share received → exclude.
- §29-29 written release: both advancee and those claiming through them excluded.

Valuation (§29-26): use the value at the earlier of (a) advancee's possession, or (b) decedent's death. If a written designation by decedent specified the value, use that.

## Step 11: Posthumous heirs (§29-9)

A child or other relative born within 10 lunar months (≈280 days) after decedent's death inherits as if born during decedent's lifetime and survived. If posthumous_birth.applicable=true and born_within_10_lunar_months=true, include them in the share computation as if alive at decedent's death. If pregnancy is known but child not yet born, set determination_status="blocked_pending_facts" and emit gap requiring birth confirmation.

## Step 12: Final share assembly and validation

After all the above:
- Sum all heir shares. They MUST equal 1.0 (i.e., 100%) unless there's an escheat. If they don't, set requires_human_review=true and explain the discrepancy.
- For each deceased heir whose share has been determined, set status="deceased_cascading" and note that a new analyst run will be triggered for that person as their own decedent.
- For each living heir confirmed by sub-agents, set status="living_confirmed".
- For each heir not yet verified as living/deceased, set status="living_unverified" and emit gap + dispatch step=10 (skip_genie_lookup) and step=20 (obituary_search).

# DISPATCH RULES

When you identify a gap, you must emit a corresponding entry in `dispatched_tasks` with the appropriate step from the Sub-Agent Step Taxonomy. Multiple gaps for the same person can be filled by multiple parallel dispatches.

Do NOT dispatch the same step for the same person if there's already a pending or completed event for it (check the events array in the input). Re-dispatch only if the prior event failed AND a different source might succeed (e.g., if obituary search failed, dispatch SSDI as fallback).

# CONFIDENCE GUIDANCE

Set `confidence` based on the weakest link in your chain of reasoning:
- "high": All relevant facts are confidence="verified" and you applied the law without ambiguity.
- "medium": One or more facts are confidence="probable" but the legal conclusion is unambiguous given those facts.
- "low": Facts are mostly probable/unverified, OR there are competing interpretations of the law given the facts.
- "unverified": Critical facts are missing or unverified to the point that conclusions are highly speculative.

# HUMAN REVIEW TRIGGERS

Set requires_human_review=true if ANY of the following apply:
- Date of death is before January 1, 1960 (pre-Ch. 29)
- Conflicting evidence about a critical fact (e.g., obituary says married, court records say divorced)
- Common-law marriage claim with formation jurisdiction unclear
- Adoption from a foreign jurisdiction with unclear NC recognition
- Slayer statute claim (always escalate)
- Heir disclaim/renunciation claim
- Advancement claim with disputed valuation
- Estate value triggers personal property floors AND value is disputed
- Pre-2012 death where personal property floors differ from current values AND those floors materially affect distribution
- Any conclusion where heir shares don't sum to 100%
- Escheat determination (always confirm with human before declaring no heirs)
- Cascade depth exceeds 4 generations (data quality concern)
- Same person identified as both ancestor and descendant in the kinship graph (data error)

# OUTPUT DISCIPLINE

- Output ONLY the JSON object. No prose. No markdown fences.
- Every numeric share MUST be expressed as both a fraction string ("1/3") and a decimal (0.3333).
- Every conclusion MUST cite a specific Ch. 29 section.
- Field names must match the schemas exactly.
- When you create new persons via new_persons_to_create, the temp_id strings let downstream code resolve them to real DB IDs after insertion.
```

### 6.2 Runtime input format

On every invocation, n8n constructs and sends this user message to the agent:

```json
{
  "invocation_context": {
    "property_id": 4521,
    "decedent_person_id": 12345,
    "triggering_event_id": "uuid-or-null",
    "triggered_by": "initial" | "sub_agent_completion" | "manual_review" | "cascade",
    "run_number": 3,
    "current_timestamp": "2026-05-08T15:30:00Z"
  },
  "decedent_state": { /* full row from v_estate_analyst_state */ },
  "all_known_persons_on_property": [
    { /* v_estate_analyst_state row per person */ }
  ],
  "prior_runs": [
    { /* full estate_analyst_runs rows for this decedent, ordered by run_number ASC */ }
  ],
  "completed_events_since_last_run": [
    { /* research_events rows where status='completed' or 'failed' and id > prior_run.last_seen_event_id */ }
  ],
  "property_cases": [
    { /* property_cases rows */ }
  ],
  "research_documents_summary": [
    { "id": 88, "document_type": "obituary", "person_id": 12345, "notes": "..." }
  ]
}
```

---

## 7. n8n Workflow Implementation

### 7.1 Trigger sources

n8n watches `research_events` table for new rows. Three trigger types:

**A. New trace started:** When an external process inserts a `research_events` row with `step=99` and `triggered_by=initial` for a new decedent, n8n picks it up and invokes the Estate Analyst.

**B. Sub-agent completion:** When any sub-agent inserts a `step=99` event after completing its work, n8n invokes the Estate Analyst.

**C. Manual re-run:** A human-review tool can insert a `step=99` event with `triggered_by=manual_review` to force re-analysis.

### 7.2 Estate Analyst invocation flow

```
1. Pick up research_events row with step=99, status='pending'
2. Mark event status='in_progress'
3. Fetch state from v_estate_analyst_state for property_id and decedent_person_id
4. Fetch prior estate_analyst_runs for this decedent (all runs ordered by run_number)
5. Determine next run_number = MAX(run_number) + 1, or 1 if first run
6. Fetch completed/failed research_events with id > prior_run.last_seen_event_id
7. Fetch property_cases for this property
8. Construct user message JSON per §6.2
9. Invoke LLM with system prompt §6.1 + user message
10. Parse LLM JSON response. If parse fails, retry once with same input.
11. Validate response against output schema (use a JSON Schema validator)
12. Begin DB transaction:
    a. INSERT into estate_analyst_runs with all the response fields
    b. For each entry in person_updates, UPDATE property_people accordingly
    c. For each entry in new_persons_to_create, INSERT property_people, capture new IDs, resolve temp_ids
    d. For each entry in relationships_to_create, INSERT property_people_relationships (resolving any temp_ids)
    e. For each entry in dispatched_tasks, INSERT research_events with status='pending'
    f. Update the triggering research_events row to status='completed'
    g. COMMIT
13. For each newly inserted research_events, n8n routes to the appropriate sub-agent based on step:
    - step 10: Skip Tracer worker
    - step 20, 21, 30, 50, 80: Verification Agent worker
    - step 40, 41, 51, 52, 53, 54, 55: Court Research Agent worker
    - step 60, 70: Deterministic compute (no LLM)
    - step 99: Re-invoke Estate Analyst (when triggered by sub-agent completion)
14. If determination_status='complete' AND every cascading branch has its own complete run AND no pending events remain → trigger Heir Tree Compiler (Phase 5 of existing workflow)
```

### 7.3 Idempotency guarantees

- The unique constraint on `(property_id, decedent_person_id, run_number)` prevents duplicate runs.
- If the workflow crashes mid-step, the in-progress event status lets n8n detect and resume.
- All `person_updates` use field-path-targeted JSONB updates (`jsonb_set`), not full-object replaces, so concurrent sub-agent writes don't clobber each other.

### 7.4 Cascade trigger logic

When the Estate Analyst marks a heir as `status="deceased_cascading"`:
1. n8n inserts a `research_events` row with `step=99`, `triggered_by=cascade`, `person_id=<the deceased heir's id>`, `payload={property_id, decedent_person_id: <deceased heir>, reason: "cascade_from_<parent_decedent_id>"}`
2. This invokes Estate Analyst with the deceased heir as the new decedent under analysis.
3. The cascade root is tracked in `research_metadata.estate_analyst_internal.cascade_root_decedent_id` for every cascade-derived person.

### 7.5 Termination conditions

The trace for a property is complete when:
- The root decedent has `determination_status='complete'`, AND
- Every heir marked `deceased_cascading` has its own `determination_status='complete'` for the cascading sub-trace, AND
- No `research_events` rows remain with `status='pending'` for any person on this property, AND
- No `requires_human_review=true` flags are unresolved.

When all four conditions are met, n8n triggers the Heir Tree Compiler.

### 7.6 Failure modes

- **Sub-agent failure (status='failed'):** Estate Analyst sees failed event in completed_events_since_last_run, decides whether to dispatch alternative source or escalate.
- **LLM JSON parse failure:** Retry once. If still fails, log error, set the triggering event to status='failed' with error message, escalate to human review.
- **Schema validation failure:** Same as parse failure.
- **Cascade depth >4 generations:** Estate Analyst itself flags requires_human_review=true. n8n still records the run but pauses further dispatches until human resolves.

---

## 8. Worked Example: End-to-End Trace

### Setup

Lydia Hayes, root decedent. Died 1985-06-04 in Wake County, NC. No will recorded. No estate case filed.

### Run 1: Initial invocation

**Input state (after Skip Tracer + Phase 1 completes):**
- `property_people` row for Lydia: `is_deceased=true`, `date_of_death=1985-06-04`, `obituary_text="Lydia Hayes died June 4, 1985. Survived by son Dennis Hayes and daughter Sharon Hayes. Preceded in death by husband Frank Hayes."`
- No relationships yet recorded.
- `research_metadata.testacy.disposition_type=null`, `research_metadata.marital_status_at_death=null`.

**Agent reasoning:**
- Testacy unknown → emit gap, dispatch step=40 (court probate search).
- Obituary text indicates "preceded in death by husband Frank Hayes" → marital_status_at_death="widowed". Emit person_update.
- Obituary text indicates two surviving children, Dennis and Sharon. Create both as new persons (new_persons_to_create), create child_of relationships.
- Cannot finalize shares until testacy confirmed (will/no will).

**Output (abbreviated):**
```json
{
  "determination_status": "blocked_pending_facts",
  "conclusions": {
    "decedent": {"person_id": 12345, "intestacy_status": "unknown_pending_court_search"},
    "heirs": [
      {"temp_id": "temp_1", "full_name": "Dennis Hayes", "status": "living_unverified", "branch_status": "blocked"},
      {"temp_id": "temp_2", "full_name": "Sharon Hayes", "status": "living_unverified", "branch_status": "blocked"}
    ]
  },
  "gaps": [
    {"subject_person_id": 12345, "fact_needed": "testacy_status", "priority": "blocking"}
  ],
  "person_updates": [
    {"person_id": 12345, "field_path": "research_metadata.marital_status_at_death.value", "new_value": "widowed", "reason": "Obituary states preceded in death by husband Frank Hayes"}
  ],
  "new_persons_to_create": [
    {"temp_id": "temp_1", "full_name": "Dennis Hayes", "person_type": "heir", "is_deceased": false},
    {"temp_id": "temp_2", "full_name": "Sharon Hayes", "person_type": "heir", "is_deceased": false}
  ],
  "relationships_to_create": [
    {"person_id": "temp_1", "related_to_person_id": 12345, "relationship_type": "child_of", "family_relationship": "biological"},
    {"person_id": "temp_2", "related_to_person_id": 12345, "relationship_type": "child_of", "family_relationship": "biological"}
  ],
  "dispatched_tasks": [
    {"step": 40, "subject_person_id": 12345, "step_name": "court_probate_search"},
    {"step": 10, "subject_person_id": "temp_1", "step_name": "skip_genie_lookup"},
    {"step": 20, "subject_person_id": "temp_1", "step_name": "obituary_search"},
    {"step": 10, "subject_person_id": "temp_2", "step_name": "skip_genie_lookup"},
    {"step": 20, "subject_person_id": "temp_2", "step_name": "obituary_search"}
  ],
  "citations": [
    {"section": "29-8", "applied_to": "intestacy_determination", "conclusion": "Cannot determine without confirming testacy status"}
  ],
  "confidence": "low",
  "confidence_rationale": "Heirs identified from obituary but not yet verified; testacy unknown"
}
```

### Run 2: After court search and skip traces complete

Court search confirms no probate case → fully intestate. Skip traces find Sharon died 2010, Dennis confirmed alive.

**Agent reasoning:**
- Testacy now confirmed: fully_intestate per §29-8.
- Spouse predeceased → no spouse share per §29-14.
- 2 surviving children at decedent's death (Dennis alive, Sharon alive in 1985, died later) → both inherit per §29-15(2).
- Each child: 1/2 share of real property per §29-16(a)(1).
- Sharon has since died → her branch cascades (status="deceased_cascading"). Need to investigate Sharon as a sub-decedent.
- Dennis confirmed living → status="living_confirmed", branch_status="resolved", ownership_percentage=0.5.

**Output (abbreviated):**
```json
{
  "determination_status": "partial",
  "conclusions": {
    "heirs": [
      {"person_id": 12346, "full_name": "Dennis Hayes", "share_fraction": "1/2", "share_decimal": 0.5, "statutory_basis": "29-15(2) + 29-16(a)(1)", "status": "living_confirmed", "branch_status": "resolved"},
      {"person_id": 12347, "full_name": "Sharon Hayes", "share_fraction": "1/2", "share_decimal": 0.5, "statutory_basis": "29-15(2) + 29-16(a)(1)", "status": "deceased_cascading", "branch_status": "cascading"}
    ],
    "totals": {"real_property_total": 1.0, "sums_to_100_percent": true}
  },
  "person_updates": [
    {"person_id": 12346, "field_path": "ownership_percentage", "new_value": 0.5, "reason": "Final share per Ch. 29-15(2) + 29-16(a)(1)"},
    {"person_id": 12347, "field_path": "research_metadata.estate_analyst_internal.branch_status", "new_value": "resolved_deceased_cascading"}
  ],
  "dispatched_tasks": [
    {"step": 99, "subject_person_id": 12347, "step_name": "estate_analyst_reanalyze", "payload_summary": "Cascade: investigate Sharon Hayes as sub-decedent"}
  ],
  "citations": [
    {"section": "29-8", "applied_to": "intestacy_confirmed", "conclusion": "No will admitted to probate; fully intestate"},
    {"section": "29-14", "applied_to": "spouse_share", "conclusion": "No spouse share; husband predeceased"},
    {"section": "29-15(2)", "applied_to": "children_share", "conclusion": "Two surviving children at decedent's death; each inherits per §29-16"},
    {"section": "29-16(a)(1)", "applied_to": "per_capita_division", "conclusion": "Estate divided by 2 (number of surviving children plus deceased children leaving descendants)"}
  ],
  "confidence": "high"
}
```

### Run 3: Cascade for Sharon Hayes

Sharon's sub-trace runs separately, identifies her two children Michael and Jennifer (both alive). Each gets 1/4 of root decedent's estate (1/2 of Sharon's 1/2 share).

When Sharon's sub-trace reaches `determination_status="complete"`, the root decedent's trace is checked: all branches resolved, no pending events → Heir Tree Compiler runs.

**Final compiled output:**
- Dennis Hayes: 50%
- Michael Hayes: 25%
- Jennifer Hayes: 25%
- Total: 100% ✓

---

## 9. Edge Cases & Human Review Triggers

The agent must flag `requires_human_review=true` for these conditions. n8n routes flagged runs to a queue for a human reviewer in TitleMatrix.

### Always escalate
- Pre-1960 date of death (Chapter 29 doesn't apply)
- Slayer statute claim (Ch. 31A)
- Escheat determination (always have a human confirm "no heirs found")
- Heir shares don't sum to 100%
- Same person appears as both ancestor and descendant (data error)
- Cascade depth >4 generations from root

### Escalate based on facts
- Conflicting evidence (obituary vs. court vs. SkipGenie disagree on a critical fact)
- Common-law marriage with unclear formation jurisdiction
- Adoption from foreign jurisdiction
- Disputed advancement valuation
- Pending divorce / equitable distribution at time of death
- Renunciation/disclaimer claim
- Pregnancy at time of death (posthumous heir possibility)
- Personal property floors materially affect distribution AND value disputed

### Operational escalations
- LLM output fails schema validation twice in a row
- Sub-agent fails for the same person more than 3 times across all sources
- A run takes longer than 60 seconds (likely runaway loop or context issue)

---

## 10. Testing & Validation

### 10.1 Unit tests for the prompt

Build a fixture set covering each Ch. 29 branch:

| Fixture | Purpose | Expected outcome |
|---|---|---|
| Single child, no spouse | §29-15(1) basic case | Child gets 100% |
| Spouse + 1 child | §29-14(a)(1) | Spouse 1/2, child 1/2 real |
| Spouse + 2 children | §29-14(a)(2) | Spouse 1/3, children 1/3 each |
| Spouse + parents (no kids) | §29-14(a)(3) | Spouse 1/2, parents split 1/2 |
| 2 children, 1 predeceased with descendants | §29-16(a)(1) per stirpes | Living child 1/2, grandchildren split other 1/2 |
| Half-blood siblings | §29-3 | Equal treatment |
| Adopted child + stepparent exception | §29-17(e) | Inherits from natural parent married to adoptive |
| Slayer | Ch. 31A | Excluded, treated as predeceased |
| Renunciation (full) | Ch. 31B | Excluded, treated as predeceased |
| Renunciation (partial) | Ch. 31B | Only renounced portion redistributed |
| Advancement equal to share | §29-25 | Excluded from further distribution |
| Out-of-wedlock child, paternity established | §29-19 | Inherits from father |
| Out-of-wedlock child, paternity NOT established | §29-19 | Inherits from mother only |
| Posthumous heir | §29-9 | Inherits as if alive at death |
| 5-degree collateral cutoff | §29-7 | Beyond cutoff excluded unless escheat backstop |
| Pre-1960 death | (out of scope) | Should escalate |
| Pregnant spouse at death | §29-9 | Should block pending birth |
| Common-law spouse from another state | NC recognition | Treats as married |
| Common-law spouse claim NC formation | NC non-recognition | No spouse share |
| Partial intestacy (will disposes of some) | §29-8 | Apply Ch. 29 to residue only |

### 10.2 Integration tests

Build at least 5 end-to-end scenarios in a staging database:
1. Simple: one decedent, two living children
2. One-level cascade: one decedent, one living child + one deceased child with descendants
3. Two-level cascade: deceased child whose own child also predeceased
4. Spouse + children
5. No descendants, collateral kin

Each test seeds the DB with the initial decedent, runs the workflow end-to-end (mocking sub-agents to return canned results), and verifies the final compiled heir tree matches the expected output.

### 10.3 Validation gates before production

- All fixture tests pass
- Integration tests pass
- An attorney reviews 10 randomly-sampled completed runs and signs off on legal correctness of citations
- No `requires_human_review=true` rate exceeding 25% on a backtest of historical traces (higher than this suggests the prompt is over-cautious)
- Average run time under 30 seconds
- Schema validation passes on 100% of LLM outputs

---

## 11. Deployment Checklist

### Infrastructure
- [ ] DDL applied: `estate_analyst_runs` table + sequence + indexes + constraints
- [ ] DDL applied: `v_estate_analyst_state` view
- [ ] JSON Schema validators implemented in application layer for `research_metadata`, `conclusions`, `gaps`, `dispatched_tasks`, `citations`
- [ ] `research_events.step` taxonomy enum/constants module created
- [ ] Sub-agent step routing logic implemented in n8n

### Agent
- [ ] System prompt deployed with version tag (e.g., `v1.0`)
- [ ] LLM provider configured (Anthropic Claude recommended; model version pinned)
- [ ] Retry policy: 1 retry on JSON parse failure, then escalate
- [ ] Logging: every run writes `model_version`, `prompt_version`, `tokens_used`, `duration_ms`

### Sub-agents
- [ ] Skip Tracer (existing) updated to write to new `research_metadata` fields where relevant
- [ ] Verification Agent updated to write `marital_status_at_death`, `survival_evaluation`
- [ ] Court Research Agent updated to write `testacy`, `paternity`, `adoption`, `legitimation`, `disqualifications` (renunciation), `advancements`
- [ ] All sub-agents emit `step=99` event on completion (success or failure)

### Workflow
- [ ] n8n workflow handles step routing per §5
- [ ] Cascade trigger logic tested
- [ ] Termination condition check implemented
- [ ] Human review queue UI built in TitleMatrix for `requires_human_review=true` runs

### Monitoring
- [ ] Dashboard: runs per day, average duration, human review rate, escheat rate, cascade depth distribution
- [ ] Alerts: schema validation failures, runs exceeding 60s, sub-agent failure spikes

### Documentation
- [ ] This spec stored in repo at `docs/estate-analyst-spec.md`
- [ ] Runbook for human reviewers describing how to resolve common review-flag types
- [ ] Onboarding doc for adding additional state law modules (the architecture is state-agnostic; only the system prompt §6.1 is NC-specific)

---

# End of Specification

Two notes for you:

1. **The system prompt in §6.1 is the longest single deliverable and the heart of the system.** That's where your dev should focus their review effort — every line of that prompt matters and should be sanity-checked by your attorney before production.

2. **For other states**, the architecture (schema, sub-agent taxonomy, n8n workflow, JSONB contracts) is state-agnostic. Only §6.1 and §10.1 fixture tests need to be rewritten per state. That's the right separation.