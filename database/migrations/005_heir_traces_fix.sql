-- Fix heir_traces for independent heir tracing
-- conclusion_id is now optional: heir tracing can run before or without a chain conclusion

-- Create heir_traces if it doesn't exist yet (idempotent)
CREATE TABLE IF NOT EXISTS heir_traces (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER NOT NULL,
    session_id          INTEGER REFERENCES heir_research_sessions(id),
    conclusion_id       INTEGER REFERENCES chain_conclusions(id),   -- nullable
    root_decedent_name  TEXT NOT NULL,
    heir_tree           JSONB NOT NULL,
    living_heir_count   INTEGER,
    total_credits_used  INTEGER,
    status              TEXT NOT NULL DEFAULT 'draft',
        -- draft | complete | manual_review | partial
    gaps                JSONB,
    fpils_synced_at     TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- If the table already existed with conclusion_id NOT NULL, drop the constraint
-- (safe to run even if already nullable)
ALTER TABLE heir_traces ALTER COLUMN conclusion_id DROP NOT NULL;

-- Add session_id column if it doesn't exist
ALTER TABLE heir_traces ADD COLUMN IF NOT EXISTS session_id INTEGER REFERENCES heir_research_sessions(id);

CREATE INDEX IF NOT EXISTS idx_ht_property_id ON heir_traces(property_id);
CREATE INDEX IF NOT EXISTS idx_ht_status      ON heir_traces(status);
CREATE INDEX IF NOT EXISTS idx_ht_session_id  ON heir_traces(session_id);
