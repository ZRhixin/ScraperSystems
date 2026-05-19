-- Heir Research Queue
-- Queue table for the webhook-self-trigger worker pattern.
-- Each row is one person to research. Workers claim items atomically
-- (SELECT FOR UPDATE SKIP LOCKED) to avoid double-processing.

CREATE TABLE IF NOT EXISTS heir_research_queue (
    id                SERIAL PRIMARY KEY,
    session_id        INTEGER NOT NULL REFERENCES heir_research_sessions(id),
    property_id       INTEGER NOT NULL REFERENCES properties(id),
    person_name       TEXT NOT NULL,
    relationship_hint TEXT,
    depth             INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'pending',
        -- pending | processing | done | failed

    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hrq_session_status ON heir_research_queue(session_id, status);
CREATE INDEX IF NOT EXISTS idx_hrq_pending        ON heir_research_queue(session_id) WHERE status = 'pending';
