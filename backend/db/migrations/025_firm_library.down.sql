-- Rollback for 025_firm_library.sql.

DROP INDEX IF EXISTS idx_chunks_firm_content;
ALTER TABLE chunks DROP COLUMN IF EXISTS firm_content_id;

DROP INDEX IF EXISTS idx_firm_content_filehash;
DROP INDEX IF EXISTS idx_firm_content_category;
DROP INDEX IF EXISTS idx_firm_content_firm_active;
DROP TABLE IF EXISTS firm_content;
