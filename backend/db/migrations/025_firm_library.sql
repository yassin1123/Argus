-- Phase 2 / Week 5 / Day 1 — firm-knowledge library.
--
-- Builds on the multi-tenancy backbone from migration 024. Each row in
-- firm_content represents one piece of firm-curated content (a sector
-- primer, a playbook, a prior engagement report, a methodology doc),
-- chunked + embedded + made available to every engagement at that firm
-- through the same hybrid_search path that already serves SEC / news /
-- transcript chunks.
--
-- A row in firm_content is the metadata; the actual content lives in
-- chunks rows linked via chunks.firm_content_id. Retiring content is a
-- soft-delete (sets retired_at); chunks stay in place so historical
-- engagement citations to a retired playbook remain valid, but the
-- retrieval-side filter (in core/retrieval_chunks.py) excludes them
-- from new searches.

CREATE TABLE IF NOT EXISTS firm_content (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN (
                        'playbook', 'sector_primer', 'prior_report',
                        'framework', 'methodology', 'other'
                    )),
    description     TEXT,
    intended_modes  TEXT[] NOT NULL DEFAULT '{}',
    sector_tags     TEXT[] NOT NULL DEFAULT '{}',
    source_filename TEXT,
    file_hash       CHAR(64),                       -- sha256 of the original bytes; powers idempotency
    trust_level     TEXT NOT NULL DEFAULT 'firm_vetted'
                        CHECK (trust_level IN ('firm_vetted', 'credible_external', 'web_general', 'contested')),
    uploaded_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retired_at      TIMESTAMPTZ,                    -- soft-delete; null = active
    retired_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_firm_content_firm_active
    ON firm_content(firm_id) WHERE retired_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_firm_content_category
    ON firm_content(firm_id, category) WHERE retired_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_firm_content_filehash
    ON firm_content(firm_id, file_hash) WHERE retired_at IS NULL;

-- chunks.firm_content_id — link from the chunks created by an ingest back
-- to the firm_content row that owns them. Nullable because pre-Week 5 chunks
-- (engagement uploads, SEC, news, transcripts, CH) have no firm_content row.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS firm_content_id UUID REFERENCES firm_content(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_firm_content
    ON chunks(firm_content_id) WHERE firm_content_id IS NOT NULL;
