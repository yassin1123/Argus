-- Phase 6: full-text search on chunks via tsvector + trigger + GIN index.
-- Hybrid retrieval combines pgvector semantic search with this BM25-ish keyword search.

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS content_tsv tsvector;

-- Backfill existing rows.
UPDATE chunks SET content_tsv = to_tsvector('english', coalesce(content, ''))
WHERE content_tsv IS NULL;

-- Auto-maintain on insert/update.
CREATE OR REPLACE FUNCTION update_chunks_tsv() RETURNS trigger AS $$
BEGIN
  NEW.content_tsv := to_tsvector('english', coalesce(NEW.content, ''));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS chunks_tsv_update ON chunks;
CREATE TRIGGER chunks_tsv_update
  BEFORE INSERT OR UPDATE OF content ON chunks
  FOR EACH ROW EXECUTE FUNCTION update_chunks_tsv();

-- GIN index for fast keyword queries.
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv ON chunks USING GIN (content_tsv);
