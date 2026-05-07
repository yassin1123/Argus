-- Rollback for 023_chunks_sec_metadata.sql.
-- Drop the SEC-specific index, then the metadata column, then re-impose
-- session_id NOT NULL. The NOT NULL re-impose will fail if SEC chunks
-- exist (session_id is null on those) — operator must purge them first.

DROP INDEX IF EXISTS idx_chunks_sec_accession;

ALTER TABLE chunks
  DROP COLUMN IF EXISTS metadata;

ALTER TABLE chunks
  ALTER COLUMN session_id SET NOT NULL;
