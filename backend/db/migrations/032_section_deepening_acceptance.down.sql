-- W9/D3 rollback.
DROP INDEX IF EXISTS idx_section_deepening_accepted;
ALTER TABLE section_deepening_runs
    DROP COLUMN IF EXISTS pre_accept_payload_snapshot,
    DROP COLUMN IF EXISTS rejected_by,
    DROP COLUMN IF EXISTS rejected_at,
    DROP COLUMN IF EXISTS accepted_by,
    DROP COLUMN IF EXISTS accepted_at;
