-- Voter record and deed finding storage for v2 workflow agents
-- Supports Vital Status Researcher (voter records) and Title Attorney (deed findings)

CREATE TABLE IF NOT EXISTS heir_voter_records (
    id           SERIAL PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES heir_research_sessions(id),
    property_id  INTEGER NOT NULL,
    person_id    INTEGER REFERENCES heir_research_persons(id),
    -- what was searched
    search_name  TEXT NOT NULL,
    search_first TEXT,
    search_last  TEXT,
    search_county TEXT,
    -- what was found (one row per voter record found)
    ncid         TEXT,
    voter_reg_num TEXT,
    full_name    TEXT,
    county       TEXT,
    city_state_zip TEXT,
    status       TEXT,        -- A=Active, I=Inactive, S=Suspended, R=Removed, D=Denied
    status_desc  TEXT,
    -- how it was used
    search_context TEXT,      -- 'vital_status_researcher' | 'surname_crosser'
    notes        TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE heir_voter_records IS
    'NC voter registration lookups saved by VSR and Surname Crosser agents';

COMMENT ON COLUMN heir_voter_records.status IS
    'A=Active (living), I=Inactive, S=Suspended, R=Removed (moved/deceased), D=Denied';

COMMENT ON COLUMN heir_voter_records.full_name IS
    'Current legal/married name on voter rolls — critical for married female heir discovery';


CREATE TABLE IF NOT EXISTS heir_deed_findings (
    id           SERIAL PRIMARY KEY,
    session_id   INTEGER NOT NULL REFERENCES heir_research_sessions(id),
    property_id  INTEGER NOT NULL,
    person_id    INTEGER REFERENCES heir_research_persons(id),
    -- person who appeared in deed records
    person_name  TEXT NOT NULL,
    county       TEXT,
    -- deed record
    book         TEXT,
    page         TEXT,
    doc_type     TEXT,
    grantor      TEXT,
    grantee      TEXT,
    recording_date TEXT,
    -- interpretation
    role         TEXT,        -- 'grantor' | 'grantee'
    significance TEXT,        -- one-sentence note from Title Attorney
    notes        TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE heir_deed_findings IS
    'Deed/grantor findings saved by Title Attorney agent for audit trail';
