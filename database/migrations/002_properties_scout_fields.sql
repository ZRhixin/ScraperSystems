-- Add Scout-extracted fields to properties table
-- These come from Prompt 1 output after the county adapter runs

ALTER TABLE properties
    ADD COLUMN IF NOT EXISTS secondary_parcel_id     VARCHAR(100),
    ADD COLUMN IF NOT EXISTS street                  TEXT,
    ADD COLUMN IF NOT EXISTS city                    VARCHAR(100),
    ADD COLUMN IF NOT EXISTS state                   VARCHAR(50),
    ADD COLUMN IF NOT EXISTS zip                     VARCHAR(20),
    ADD COLUMN IF NOT EXISTS current_owners          JSONB,      -- array of {raw_name, owner_order}
    ADD COLUMN IF NOT EXISTS short_legal_raw         TEXT,
    ADD COLUMN IF NOT EXISTS subdivision             VARCHAR(255),
    ADD COLUMN IF NOT EXISTS block                   VARCHAR(50),
    ADD COLUMN IF NOT EXISTS lot                     VARCHAR(50),
    ADD COLUMN IF NOT EXISTS plat_book               VARCHAR(50),
    ADD COLUMN IF NOT EXISTS plat_page               VARCHAR(50),
    ADD COLUMN IF NOT EXISTS full_legal_description  TEXT,
    ADD COLUMN IF NOT EXISTS last_sale_date          DATE,
    ADD COLUMN IF NOT EXISTS extraction_notes        JSONB;
