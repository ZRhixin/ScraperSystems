-- Heir Research Schema
-- Tables for the heir tracer n8n workflow (Steps 3-5)
-- Neon DB (ScraperSystems) — independent from FPILS/realestate DB

-- ============================================================
-- HEIR RESEARCH SESSIONS
-- One row per heir tracing run per property.
-- Created by the Code in JavaScript node before the loop starts.
-- ============================================================
CREATE TABLE IF NOT EXISTS heir_research_sessions (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER NOT NULL REFERENCES properties(id),
    conclusion_id       INTEGER REFERENCES chain_conclusions(id),  -- nullable: tracing can run before chain workflow
    root_decedent_name  TEXT NOT NULL,
    root_decedent_dod   TEXT,

    status              TEXT NOT NULL DEFAULT 'in_progress',
        -- in_progress | complete | manual_review | partial

    -- Filled after all research is complete
    intestate_analysis  JSONB,              -- Intestate Expert's full NC Ch. 29 output
    heir_tree           JSONB,              -- Final compiled heir tree with shares
    living_heir_count   INTEGER,
    total_credits_used  INTEGER,
    gaps                JSONB DEFAULT '[]',

    fpils_synced_at     TIMESTAMPTZ,        -- Set when synced to FPILS property_people
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hrs_property_id ON heir_research_sessions(property_id);
CREATE INDEX IF NOT EXISTS idx_hrs_status      ON heir_research_sessions(status);

-- ============================================================
-- HEIR RESEARCH PERSONS
-- One row per relative the Orchestrator processes during the loop.
-- Written by the Orchestrator (via Write Family Tree Database tool)
-- after it completes all research phases for that relative.
-- ============================================================
CREATE TABLE IF NOT EXISTS heir_research_persons (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES heir_research_sessions(id),
    property_id     INTEGER NOT NULL REFERENCES properties(id),

    -- Input from Root Owner Research relative list
    input_name          TEXT NOT NULL,
    relationship_hint   TEXT,
    age_estimate        TEXT,
    phone               TEXT,
    input_address       TEXT,

    -- SkipGenie matched identity
    matched_full_name   TEXT,
    matched_dob         TEXT,
    matched_dod         TEXT,
    matched_address     TEXT,
    match_confidence    TEXT,   -- high | medium | low

    -- Vital status (confirmed after obituary + SkipGenie)
    vital_status        TEXT,   -- living | deceased | unknown

    -- NC Ch. 29 required facts (only populated for deceased persons)
    date_of_death               TEXT,
    marital_status_at_death     TEXT,
    surviving_spouse_name       TEXT,
    estate_filed                BOOLEAN,
    had_will                    BOOLEAN,
    family_alive_at_death       JSONB DEFAULT '[]',

    -- Deed / transfer findings
    deed_transfers              JSONB DEFAULT '[]',

    -- Whether this person is deceased with unresolved heirs (triggers cascade)
    cascade_needed              BOOLEAN NOT NULL DEFAULT FALSE,

    -- Filled by Intestate Expert after the loop completes
    computed_share_percentage   DECIMAL(10, 6),
    share_fraction              TEXT,       -- e.g. "1/3"
    branch_status               TEXT,
        -- living_confirmed | deceased_resolved | cascade_pending | disqualified | renounced | escheat_branch

    -- Full raw Orchestrator JSON output (for audit trail)
    orchestrator_output         JSONB,

    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hrp_session_id     ON heir_research_persons(session_id);
CREATE INDEX IF NOT EXISTS idx_hrp_property_id    ON heir_research_persons(property_id);
CREATE INDEX IF NOT EXISTS idx_hrp_vital_status   ON heir_research_persons(vital_status);
CREATE INDEX IF NOT EXISTS idx_hrp_cascade_needed ON heir_research_persons(cascade_needed);
