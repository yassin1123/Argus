-- Run manually if DB was created before this migration (Docker init only runs 001 on fresh volume).
ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS chunk_meta JSONB DEFAULT '{}';
ALTER TABLE reports ADD COLUMN IF NOT EXISTS evidence_bundle JSONB DEFAULT '[]';
