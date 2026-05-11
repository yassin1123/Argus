-- W8/D2 rollback.
DROP INDEX IF EXISTS idx_sessions_mece_overlaps_count;
ALTER TABLE sessions DROP COLUMN IF EXISTS mece_overlaps_count;
