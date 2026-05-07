-- Phase 1 / Week 3 / Day 3 — SEC EDGAR ingestion needs to attach per-filing
-- breadcrumbs (cik / form / accession_number / filing_date / item_id /
-- char_offset_in_filing / primary_doc_url) to each chunk so the verifier
-- can produce a "open the source at this exact spot" citation.
--
-- The Day 3 spec assumed `chunks.metadata jsonb` already existed; the
-- actual schema only had typed location fields (page / slide / timestamp_str
-- etc.) which can't carry the SEC-specific breadcrumbs without losing
-- information. This migration adds the jsonb generically so any future
-- retriever (Companies House, news, etc.) can use it without further
-- schema work.
--
-- Two changes, both additive / nullable:
--   1. metadata JSONB defaulted to '{}'::jsonb — every chunk row gets one.
--   2. session_id loses NOT NULL — SEC content is firm-global, not session-
--      scoped. Existing rows already have non-null session_id; the constraint
--      relaxation only affects new SEC inserts that pass NULL.
-- A targeted partial index on metadata->>'accession_number' speeds up the
-- accession-level idempotency check in core/retrievers/edgar/ingest.py.

ALTER TABLE chunks
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE chunks
  ALTER COLUMN session_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_sec_accession
  ON chunks ((metadata->>'accession_number'))
  WHERE source_type = 'sec_filing';
