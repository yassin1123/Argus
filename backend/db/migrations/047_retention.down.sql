DROP INDEX IF EXISTS idx_purge_audit_session;
DROP INDEX IF EXISTS idx_purge_audit_firm_time;
DROP TABLE IF EXISTS purge_audit_log;
ALTER TABLE sessions
    DROP COLUMN IF EXISTS retention_grace_expires_at,
    DROP COLUMN IF EXISTS retention_flagged_at;
ALTER TABLE firms DROP COLUMN IF EXISTS retention_days;
