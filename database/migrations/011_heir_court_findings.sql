-- Court document findings — probate data extracted by Title Attorney via Court Document Pull
-- Written by Title Attorney after successful PDF extraction from NC courts portal.
-- Read by Family Assembler to build relationship maps from legally sworn filings.

CREATE TABLE IF NOT EXISTS heir_court_findings (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES heir_research_sessions(id),
    property_id     INTEGER NOT NULL,
    person_id       INTEGER REFERENCES heir_research_persons(id),

    -- The person whose estate was searched
    person_name     TEXT NOT NULL,

    -- Court case metadata
    case_number     TEXT,
    case_url        TEXT,
    case_type       TEXT,       -- 'E' (Estate) | 'SP' (Special Proceedings)
    estate_filed    BOOLEAN,
    had_will        BOOLEAN,    -- true=testate, false=intestate, null=unknown

    -- Extracted from probate PDF via Court Document Pull
    probate_family_tree     JSONB DEFAULT '[]',  -- [{name, generation, vital_status, has_issue, parent_of, notes}]
    probate_no_issue        JSONB DEFAULT '[]',  -- [name, ...] confirmed has_issue=false (branch extinct)
    named_persons           JSONB DEFAULT '[]',  -- [{name, relationship, vital_status, share, address, notes}]
    documents               JSONB DEFAULT '[]',  -- full extraction array from pull_court_document

    -- Decedent info from the filing
    decedent_name       TEXT,
    decedent_dod        TEXT,
    document_type       TEXT,   -- 'application' | 'family_tree' | 'other'
    extraction_summary  TEXT,

    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hcf_session_id  ON heir_court_findings(session_id);
CREATE INDEX IF NOT EXISTS idx_hcf_property_id ON heir_court_findings(property_id);
CREATE INDEX IF NOT EXISTS idx_hcf_person_id   ON heir_court_findings(person_id);
CREATE INDEX IF NOT EXISTS idx_hcf_person_name ON heir_court_findings(person_name);

COMMENT ON TABLE heir_court_findings IS
    'Probate court document extractions saved by Title Attorney. '
    'probate_family_tree is the primary source for Family Assembler relationship mapping. '
    'has_issue=false entries confirm branches with no living heirs.';

COMMENT ON COLUMN heir_court_findings.probate_family_tree IS
    'Array of family members from the probate PDF. '
    'generation: 0=decedent, positive=descendants, negative=ancestors. '
    'has_issue: false=confirmed no children (branch extinct), true=has children, null=unknown.';

COMMENT ON COLUMN heir_court_findings.probate_no_issue IS
    'Names confirmed has_issue=false — branches with no living heirs. '
    'Critical for Intestate Expert: skip cascading into these branches.';
