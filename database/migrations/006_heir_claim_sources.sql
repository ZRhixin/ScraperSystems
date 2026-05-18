-- Migration 006: Add source-of-evidence columns to heir_research_persons
-- Stores proof/attribution for each of the 5 NC Ch. 29 required facts.

ALTER TABLE heir_research_persons
    ADD COLUMN IF NOT EXISTS obituary_url    TEXT,
    ADD COLUMN IF NOT EXISTS obituary_text   TEXT,
    ADD COLUMN IF NOT EXISTS claim_sources   JSONB NOT NULL DEFAULT '{}';

COMMENT ON COLUMN heir_research_persons.obituary_url  IS 'URL of the obituary or death notice found during research';
COMMENT ON COLUMN heir_research_persons.obituary_text IS 'Extracted text / excerpt from the obituary';
COMMENT ON COLUMN heir_research_persons.claim_sources IS
$$Evidence attribution for each NC Ch. 29 required fact.
Shape:
{
  "date_of_death": {
    "value": "2021-03-15",
    "source": "obituary | skipgenie | court | death_cert | unknown",
    "url": "optional",
    "confidence": "high | medium | low | none"
  },
  "marital_status_at_death": {
    "value": "married | widowed | divorced | single",
    "source": "obituary | skipgenie | court | unknown",
    "confidence": "high | medium | low | none"
  },
  "estate_filed": {
    "value": true,
    "source": "nc_courts | unknown",
    "case_numbers": ["25SP003364-590"],
    "confidence": "high | low"
  },
  "had_will": {
    "value": null,
    "source": "register_of_actions | nc_courts | unknown",
    "confidence": "high | medium | low | none"
  },
  "family_alive_at_death": {
    "sources": ["obituary", "skipgenie"],
    "confidence": "high | medium | low | none"
  }
}$$;
