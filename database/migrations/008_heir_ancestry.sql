-- Ancestry Records — findings from Ancestry.com searches during heir research
-- Written by the Obituary Researcher agent via Write Ancestry Findings tool.
-- Read by the Family Assembler agent via Load Ancestry Records tool.

CREATE TABLE IF NOT EXISTS heir_ancestry_records (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES heir_research_sessions(id),
    property_id     INTEGER NOT NULL REFERENCES properties(id),
    person_id       INTEGER REFERENCES heir_research_persons(id),

    -- Who was searched
    search_name         TEXT NOT NULL,
    search_first        TEXT,
    search_last         TEXT,
    search_birth_year   TEXT,
    search_death_year   TEXT,
    search_state        TEXT DEFAULT 'NC',

    -- Ancestry record fields (normalized from search result)
    record_id       TEXT,
    collection_id   TEXT,
    record_type     TEXT,   -- e.g. Death, Census, Birth, Obituary
    collection      TEXT,   -- e.g. "North Carolina Death Certificates"

    person_name     TEXT,
    dob             TEXT,
    dod             TEXT,
    birth_location  TEXT,
    death_location  TEXT,
    spouse_name     TEXT,
    parents         JSONB DEFAULT '[]',
    children        JSONB DEFAULT '[]',
    siblings        JSONB DEFAULT '[]',
    residence       TEXT,
    source_url      TEXT,
    confidence      TEXT,   -- high | medium (from Ancestry viewable flag)
    has_image       BOOLEAN,
    viewable        BOOLEAN,

    -- Agent's relevance judgment
    relevance       TEXT,   -- confirmed | likely | possible | rejected
    relevance_notes TEXT,

    raw_data        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_har_session_id   ON heir_ancestry_records(session_id);
CREATE INDEX IF NOT EXISTS idx_har_property_id  ON heir_ancestry_records(property_id);
CREATE INDEX IF NOT EXISTS idx_har_person_id    ON heir_ancestry_records(person_id);
CREATE INDEX IF NOT EXISTS idx_har_search_name  ON heir_ancestry_records(search_name);
CREATE INDEX IF NOT EXISTS idx_har_relevance    ON heir_ancestry_records(relevance);
