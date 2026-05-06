-- Add short_legal_parsed to properties
-- Property Researcher outputs both raw and parsed forms of the short legal description.
-- short_legal_raw already exists (002). This adds the parsed counterpart.

ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS short_legal_parsed TEXT;
