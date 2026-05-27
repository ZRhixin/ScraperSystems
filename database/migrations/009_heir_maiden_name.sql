-- Maiden name tracking for married female heirs
-- Allows re-searching under birth surname when married name is discovered.

ALTER TABLE heir_research_persons
    ADD COLUMN IF NOT EXISTS maiden_name TEXT;

ALTER TABLE heir_research_queue
    ADD COLUMN IF NOT EXISTS maiden_name TEXT;

COMMENT ON COLUMN heir_research_persons.maiden_name IS
    'Birth/maiden surname if person married and changed name (e.g. HAYES for CARRIE HAYES WILKERSON)';

COMMENT ON COLUMN heir_research_queue.maiden_name IS
    'Birth/maiden surname hint passed from cascade source for re-searching under birth name';
