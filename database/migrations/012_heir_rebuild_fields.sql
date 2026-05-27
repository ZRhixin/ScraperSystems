-- Migration 012: Level-based branch tracking for v3 heir tracer rebuild
-- Adds fields needed for progressive DB writes and branch-first traversal

-- ============================================================
-- heir_research_persons — level, branch, progressive research fields
-- ============================================================
ALTER TABLE heir_research_persons
    ADD COLUMN IF NOT EXISTS level                    INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS branch_id               TEXT,
    ADD COLUMN IF NOT EXISTS parent_person_id        INTEGER REFERENCES heir_research_persons(id),
    ADD COLUMN IF NOT EXISTS vital_status_paused     BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS obituary_named_survivors JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS ancestry_named_children  JSONB DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS research_phase          TEXT NOT NULL DEFAULT 'pending';

COMMENT ON COLUMN heir_research_persons.level IS
    '0 = root decedent, 1 = root heirs, 2 = deceased heir children, etc.';

COMMENT ON COLUMN heir_research_persons.branch_id IS
    'Identifier for which per-stirpes branch this person belongs to (e.g. TROY_HAYES)';

COMMENT ON COLUMN heir_research_persons.parent_person_id IS
    'person_id of the person who triggered this cascade (NULL for root and level-1)';

COMMENT ON COLUMN heir_research_persons.vital_status_paused IS
    'TRUE when vital_status=unknown and branch is paused pending human review';

COMMENT ON COLUMN heir_research_persons.obituary_named_survivors IS
    'Named individuals from verified obituary text — primary cascade source';

COMMENT ON COLUMN heir_research_persons.ancestry_named_children IS
    'Children identified from Ancestry records — secondary cascade source';

COMMENT ON COLUMN heir_research_persons.research_phase IS
    'Enum: pending|skipgenie|vital_status|obituary|court|complete|paused';

CREATE INDEX IF NOT EXISTS idx_hrp_level        ON heir_research_persons(session_id, level);
CREATE INDEX IF NOT EXISTS idx_hrp_parent       ON heir_research_persons(parent_person_id);
CREATE INDEX IF NOT EXISTS idx_hrp_paused       ON heir_research_persons(session_id) WHERE vital_status_paused = TRUE;

-- ============================================================
-- heir_research_queue — source tracking and branch context
-- ============================================================
ALTER TABLE heir_research_queue
    ADD COLUMN IF NOT EXISTS source          TEXT NOT NULL DEFAULT 'seed',
    ADD COLUMN IF NOT EXISTS branch_id       TEXT,
    ADD COLUMN IF NOT EXISTS parent_person_id INTEGER;

COMMENT ON COLUMN heir_research_queue.source IS
    'seed | cascade_skipgenie | cascade_obit | cascade_ancestry | cascade_probate';

-- ============================================================
-- heir_research_sessions — branch plan and phase tracking
-- ============================================================
ALTER TABLE heir_research_sessions
    ADD COLUMN IF NOT EXISTS branch_plan     JSONB,
    ADD COLUMN IF NOT EXISTS paused_count    INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS research_phase  TEXT NOT NULL DEFAULT 'root_research';

COMMENT ON COLUMN heir_research_sessions.branch_plan IS
    'Branch Planner Agent output: initial per-stirpes heir list with NC Ch. 29 rationale';

COMMENT ON COLUMN heir_research_sessions.paused_count IS
    'Number of branches currently paused due to unknown vital status';

COMMENT ON COLUMN heir_research_sessions.research_phase IS
    'Enum: root_research | worker_loop | family_assembly | complete';
