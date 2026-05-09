-- Rollback for 024_firm_multitenancy.sql.

ALTER TABLE chunks DROP COLUMN IF EXISTS firm_id;
DROP INDEX IF EXISTS idx_chunks_firm;
DROP INDEX IF EXISTS idx_chunks_firm_source_type;

ALTER TABLE uploaded_files DROP COLUMN IF EXISTS firm_id;
DROP INDEX IF EXISTS idx_uploaded_files_firm;

ALTER TABLE sessions DROP COLUMN IF EXISTS firm_id;
DROP INDEX IF EXISTS idx_sessions_firm;

ALTER TABLE users DROP COLUMN IF EXISTS default_firm_id;

DROP TABLE IF EXISTS firm_memberships;
DROP TABLE IF EXISTS firms;
