# FPILS CRM — Realestate Backend

**Location:** `C:\Users\Summer Ishi\Github\TitleMatrix\realestate\backend`  
**Framework:** FastAPI + PostgreSQL  
**DB:** Local PostgreSQL (`localhost:5432/property_database` per template)  
**Frontend:** React at `realestate/frontend`  
**API Base:** `http://localhost:8000` (backend port — different from ScraperSystems port 8000; run on different machines or ports)

FPILS = **Fact Pattern & Interest Ledger System**. The realestate CRM is where all human-facing research lives: property people, heir deals, family trees, facts, and computed ownership shares.

## Key Tables in FPILS DB

### `property_people` — Unified person table
Every person related to a property (owners, heirs, relatives, associates, attorneys).

Key columns:
- `id, property_id, person_type` — 'owner' | 'heir' | 'relative' | 'associate' | 'attorney' | 'other'
- `is_deceased, full_name, first_name, last_name`
- `date_of_birth, date_of_death, place_of_death`
- `obituary_link, obituary_text`
- `probate_status, estate_status, court_county, probate_case_number`
- `research_status` — 'not_started' | 'need_to_research' | 'in_progress' | 'needs_genealogist' | 'completed' | 'blocked'
- `research_metadata JSONB` — all estate analyst findings (marital status, testacy, adoption, paternity, etc.)
- `ownership_percentage DECIMAL`
- `excluded_from_computation BOOLEAN` — for slayer rule / disclaimer / paternity exclusions
- Skip trace fields: `estimated_birth_year, birth_year_range, time_at_address, previous_addresses, possible_relatives, possible_associates`

### `property_people_relationships` — Family relationships
- `person_id, related_to_person_id, relationship_type, family_relationship`
- `marriage_end_reason, marriage_end_date, marriage_sequence`
- family_relationship values: 'spouse', 'former_spouse', 'child', 'sibling', etc.

### `research_events` — Step-based task queue (CRITICAL for heir tracer)
The event queue that drives the heir tracer workflow. n8n polls this table.

Key columns:
- `id UUID, person_id, property_id`
- `step SMALLINT` — see taxonomy in estate analyst spec (10=SkipGenie, 20=obituary, 30=SSDI, 40=court, 99=re-analyze)
- `payload JSONB` — agent-specific parameters
- `status` — 'pending' | 'completed' | 'failed'
- `user_id` (system user for automation)
- `created_at, updated_at`

### `facts` — FPILS fact records
Immutable audit trail of every known fact about a person/property.

Key fact_types (relevant to heir tracing):
- `date_of_death, date_of_birth, state_of_domicile`
- `marital_status_at_death, spouse_at_death, has_children, is_alive`
- `will_exists, will_recorded, will_validity_status, will_admitted_to_probate`
- `probate_opened, probate_case_filed, probate_case_reference`
- `is_biological_child, is_legally_adopted, half_blood`
- `marriage_legally_valid, divorce_finalized`
- Fact-Gate facts: `estate_exists, beneficiaries_identified, estate_final_accounting`

Confidence levels: `"assumed"` | `"probable"` | `"verified"` | `"disputed"`

### `estate_analyst_runs` — **NEEDS TO BE CREATED**
See full DDL in `05_estate_analyst_spec.md`. Must be added to FPILS DB as a migration.

### `estate_computations` — FPILS share calculations
FPILS engine output. Status: 'draft' | 'blocked' | 'final' | 'superseded'.
Contains `computed_heirs JSONB`, `blockers JSONB`, `transition_chain JSONB`.

### `interest_ledger_entries` — Per-person share ledger
One row per person per computation. Has `share_numerator, share_denominator, share_percentage, trace JSONB`.

### `research_documents` — Evidence files
Attached evidence (obituaries, court records, etc.) linked to persons/facts.

### `property_cases` — Probate/estate court cases
Court case records linked to property and person.

## Key API Endpoints (for n8n to call)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/property-people` | Create person (heir, owner, relative) |
| `GET` | `/api/v1/property-people/property/{id}` | Get all people for a property |
| `PATCH` | `/api/v1/property-people/{id}` | Update person (DOD, research_metadata, etc.) |
| `POST` | `/api/v1/property-people/{id}/relationships` | Add relationship |
| `POST` | `/api/v1/facts` | Create a fact |
| `GET` | `/api/v1/facts/property/{id}` | List active facts for property |
| `POST` | `/api/v1/facts/{id}/supersede` | Replace a fact with corrected version |
| `POST` | `/api/v1/facts/{id}/evidence` | Attach evidence to a fact |
| `POST` | `/computations/property/{id}/recompute` | Trigger FPILS share recompute |
| `GET` | `/computations/property/{id}` | Get current computation (shares) |

## research_metadata JSONB Schema

The `property_people.research_metadata` field is the Estate Analyst's working state per person. Key sub-fields:
- `marital_status_at_death` — value, spouse_person_id, confidence, evidence_url
- `testacy` — had_will, disposition_type, probate_case_id, confidence
- `adoption` — is_adopted, adopted_by_person_ids, confidence
- `paternity` — born_out_of_wedlock, father_established, establishment_method
- `disqualifications[]` — slayer, renunciation entries
- `survival_evaluation` — survived_decedent, survived_120_hours
- `estate_analyst_internal` — branch_status, last_run_id, cascade_root_decedent_id

## FPILS Computation Flow

1. Facts are created/updated (by agents or manually)
2. POST `/computations/property/{id}/recompute` triggers the rule engine
3. Engine reads all active facts + `property_people` + relationships
4. Applies NC Ch. 29 rules to produce `estate_computations` + `interest_ledger_entries`
5. Status starts as 'draft' or 'blocked' (if facts are missing)
6. Researcher reviews and can finalize

## Authentication Note

The realestate API requires JWT auth. The heir tracer n8n workflow needs a system/automation user JWT to call these endpoints. Store as n8n credential.
