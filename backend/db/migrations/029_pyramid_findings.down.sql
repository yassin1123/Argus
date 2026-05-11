-- W8/D1 rollback.
DROP INDEX IF EXISTS idx_sessions_pyramid_findings_count;
ALTER TABLE sessions DROP COLUMN IF EXISTS pyramid_findings_count;
