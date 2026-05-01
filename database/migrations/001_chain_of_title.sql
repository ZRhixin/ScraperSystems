-- Chain of Title Schema
-- Scraper DB — fully independent from realestate/FPILS
-- Run once against the Neon PostgreSQL instance

-- ============================================================
-- PROPERTIES (lightweight anchor — not the FPILS properties table)
-- ============================================================
CREATE TABLE IF NOT EXISTS properties (
    id            SERIAL PRIMARY KEY,
    parcel_id     VARCHAR(100) NOT NULL,
    county        VARCHAR(100) NOT NULL,
    state_code    VARCHAR(2)   NOT NULL DEFAULT 'NC',
    address       TEXT,
    scout_completed_at    TIMESTAMP,
    investigation_status  VARCHAR(20) DEFAULT 'pending',
    chain_conclusion_id   INTEGER,         -- FK added after chain_conclusions is created
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (parcel_id, county, state_code)
);

-- ============================================================
-- APPRAISER TRANSFER HISTORY
-- Scout writes; Investigate Phase A verifies each row.
-- ============================================================
CREATE TABLE IF NOT EXISTS appraiser_transfer_history (
    id                  SERIAL PRIMARY KEY,
    property_id         INTEGER NOT NULL REFERENCES properties(id),
    book                VARCHAR(50),
    page                VARCHAR(50),
    instrument_number   VARCHAR(100),
    recorded_date       DATE,
    grantor_raw         TEXT,
    grantee_raw         TEXT,
    short_legal_raw     TEXT,
    verification_status VARCHAR(30) NOT NULL DEFAULT 'pending',
        -- pending | verified | verified_with_discrepancy | not_findable
    verification_notes  TEXT,
    verified_at         TIMESTAMP,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ath_property_id ON appraiser_transfer_history(property_id);
CREATE INDEX idx_ath_verification_status ON appraiser_transfer_history(verification_status);

-- ============================================================
-- ROD CAPTURES
-- Raw captures from Register of Deeds. Immutable once written.
-- ============================================================
CREATE TABLE IF NOT EXISTS rod_captures (
    id                SERIAL PRIMARY KEY,
    property_id       INTEGER NOT NULL REFERENCES properties(id),
    source_url        TEXT,
    capture_type      VARCHAR(30) NOT NULL,
        -- grantee_search_result | grantor_search_result | document_image | index_page
    book              VARCHAR(50),
    page              VARCHAR(50),
    instrument_number VARCHAR(100),
    raw_content       TEXT,               -- file path or raw text
    ocr_text          TEXT,
    ocr_confidence    NUMERIC(4,3),
    captured_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    parse_status      VARCHAR(20) NOT NULL DEFAULT 'captured',
        -- captured | extracted | failed | needs_human
    parse_error       TEXT,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rod_captures_property_id ON rod_captures(property_id);
CREATE INDEX idx_rod_captures_parse_status ON rod_captures(parse_status);
CREATE INDEX idx_rod_captures_book_page ON rod_captures(book, page);

-- ============================================================
-- COURT CAPTURES
-- Raw captures from Clerk of Superior Court.
-- ============================================================
CREATE TABLE IF NOT EXISTS court_captures (
    id                SERIAL PRIMARY KEY,
    property_id       INTEGER NOT NULL REFERENCES properties(id),
    source_url        TEXT,
    capture_type      VARCHAR(30) NOT NULL,
    court_case_number VARCHAR(100),
    document_type     VARCHAR(100),
    raw_content       TEXT,
    ocr_text          TEXT,
    ocr_confidence    NUMERIC(4,3),
    captured_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    parse_status      VARCHAR(20) NOT NULL DEFAULT 'captured',
        -- captured | extracted | failed | needs_human
    parse_error       TEXT,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_court_captures_property_id ON court_captures(property_id);
CREATE INDEX idx_court_captures_parse_status ON court_captures(parse_status);
CREATE INDEX idx_court_captures_case_number ON court_captures(court_case_number);

-- ============================================================
-- DOCUMENT EXTRACTIONS
-- Structured fields extracted from one captured document.
-- Must reference either a rod_capture or court_capture.
-- ============================================================
CREATE TABLE IF NOT EXISTS document_extractions (
    id                          SERIAL PRIMARY KEY,
    property_id                 INTEGER NOT NULL REFERENCES properties(id),
    rod_capture_id              INTEGER REFERENCES rod_captures(id),
    court_capture_id            INTEGER REFERENCES court_captures(id),
    document_type               VARCHAR(50),
        -- warranty_deed | quitclaim | corrective_deed | deed_of_distribution |
        -- deed_of_trust | mortgage | release | lis_pendens | judgment_lien |
        -- affidavit_of_death | estate_order | other
    grantor_names               JSONB,
    grantee_names               JSONB,
    recorded_date               DATE,
    instrument_date             DATE,
    book                        VARCHAR(50),
    page                        VARCHAR(50),
    instrument_number           VARCHAR(100),
    vesting_language            TEXT,
    legal_description_full      TEXT,
    legal_description_short     TEXT,
    plat_book                   VARCHAR(50),
    plat_page                   VARCHAR(50),
    conveys_multiple_parcels    BOOLEAN NOT NULL DEFAULT FALSE,
    parcels_conveyed_count      INTEGER DEFAULT 1,
    references_prior_deed_book  VARCHAR(50),
    references_prior_deed_page  VARCHAR(50),
    references_prior_deed_language TEXT,
    legal_match_to_parcel       VARCHAR(10),    -- high | medium | low | none
    legal_match_method          VARCHAR(30),    -- plat_reference | metes_bounds | narrative | chain_logic_only | none
    legal_match_notes           TEXT,
    extraction_confidence       VARCHAR(10),    -- high | medium | low
    summary                     TEXT,
    flags                       JSONB NOT NULL DEFAULT '[]',
    created_at                  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_capture_ref CHECK (
        rod_capture_id IS NOT NULL OR court_capture_id IS NOT NULL
    )
);

CREATE INDEX idx_doc_extractions_property_id ON document_extractions(property_id);
CREATE INDEX idx_doc_extractions_rod_capture ON document_extractions(rod_capture_id);
CREATE INDEX idx_doc_extractions_court_capture ON document_extractions(court_capture_id);
CREATE INDEX idx_doc_extractions_document_type ON document_extractions(document_type);
CREATE INDEX idx_doc_extractions_legal_match ON document_extractions(legal_match_to_parcel);

-- ============================================================
-- INVESTIGATION SESSIONS
-- One row per property investigation.
-- ============================================================
CREATE TABLE IF NOT EXISTS investigation_sessions (
    id              SERIAL PRIMARY KEY,
    property_id     INTEGER NOT NULL REFERENCES properties(id),
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
        -- pending | in_progress | settled | flagged_for_review
    current_phase   VARCHAR(5),     -- A | B | C | D | E | done
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    iteration_count INTEGER NOT NULL DEFAULT 0,
    stop_reason     TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_inv_sessions_property_id ON investigation_sessions(property_id);
CREATE INDEX idx_inv_sessions_status ON investigation_sessions(status);

-- ============================================================
-- INVESTIGATION QUESTIONS
-- Open/resolved questions the investigator is chasing.
-- ============================================================
CREATE TABLE IF NOT EXISTS investigation_questions (
    id              SERIAL PRIMARY KEY,
    session_id      INTEGER NOT NULL REFERENCES investigation_sessions(id),
    question        TEXT NOT NULL,
    actions_taken   JSONB NOT NULL DEFAULT '[]',
    resolution      VARCHAR(25),    -- resolved | unresolved_flagged | abandoned
    resolution_notes TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_inv_questions_session_id ON investigation_questions(session_id);
CREATE INDEX idx_inv_questions_resolution ON investigation_questions(resolution);

-- ============================================================
-- INVESTIGATION TRACE
-- Append-only audit log. Never update rows — only insert.
-- ============================================================
CREATE TABLE IF NOT EXISTS investigation_trace (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES investigation_sessions(id),
    step_number INTEGER NOT NULL,
    action      TEXT NOT NULL,
    input       JSONB,
    output      JSONB,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
    -- no updated_at — this table is append-only
);

CREATE INDEX idx_inv_trace_session_id ON investigation_trace(session_id);
CREATE INDEX idx_inv_trace_session_step ON investigation_trace(session_id, step_number);

-- ============================================================
-- INCIDENTAL RECORDS
-- Mortgages, liens, releases, lis pendens found during investigation.
-- Captured and summarized — not chain-analyzed.
-- ============================================================
CREATE TABLE IF NOT EXISTS incidental_records (
    id              SERIAL PRIMARY KEY,
    property_id     INTEGER NOT NULL REFERENCES properties(id),
    extraction_id   INTEGER NOT NULL REFERENCES document_extractions(id),
    record_type     VARCHAR(50),
    summary         TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_incidental_property_id ON incidental_records(property_id);

-- ============================================================
-- CHAIN CONCLUSIONS
-- Final output per property. Supersede — never overwrite.
-- ============================================================
CREATE TABLE IF NOT EXISTS chain_conclusions (
    id                      SERIAL PRIMARY KEY,
    property_id             INTEGER NOT NULL REFERENCES properties(id),
    status                  VARCHAR(15) NOT NULL DEFAULT 'active',
        -- active | superseded
    current_owners          JSONB,
    acquisition_type        VARCHAR(40),
        -- deed | inheritance_with_deed_of_distribution | inheritance_court_only | unresolved
    acquisition_document_refs JSONB,
    vesting                 VARCHAR(25),
        -- sole | tenancy_by_entirety | jtwros | tenants_in_common | trust | entity | unresolved
    vesting_evidence        JSONB,
    legal_description_confidence VARCHAR(10),    -- high | medium | low
    supporting_document_refs JSONB,
    flags                   JSONB NOT NULL DEFAULT '[]',
    verify_status           VARCHAR(25) NOT NULL DEFAULT 'pending',
        -- pending | approved | objection_raised | flagged_for_human
    verify_objections       JSONB,
    superseded_by_id        INTEGER REFERENCES chain_conclusions(id),
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chain_conclusions_property_id ON chain_conclusions(property_id);
CREATE INDEX idx_chain_conclusions_status ON chain_conclusions(status);
CREATE INDEX idx_chain_conclusions_verify_status ON chain_conclusions(verify_status);

-- ============================================================
-- BACK-FILL: chain_conclusion_id on properties
-- Done after chain_conclusions exists to avoid forward-reference
-- ============================================================
ALTER TABLE properties
    ADD CONSTRAINT fk_properties_chain_conclusion
    FOREIGN KEY (chain_conclusion_id) REFERENCES chain_conclusions(id);
