-- Migration 013: Add contact_phones and contact_emails to heir_research_persons
-- These are populated by the SkipGenie Resolver for outreach to living heirs.
ALTER TABLE heir_research_persons
    ADD COLUMN IF NOT EXISTS contact_phones  JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS contact_emails  JSONB DEFAULT '[]'::jsonb;
