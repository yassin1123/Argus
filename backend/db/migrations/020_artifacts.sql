-- Phase 9: artifacts as first-class entities (memo / deck / model / chart).
-- Decoupled from `reports` — a single engagement may have many artifacts.

CREATE TABLE IF NOT EXISTS artifacts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    type          TEXT NOT NULL CHECK (type IN ('memo', 'deck', 'model', 'chart')),
    title         TEXT NOT NULL DEFAULT 'Untitled',
    status        TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'review', 'final')),
    -- ProseMirror / TipTap JSON document (memo) or domain-specific shape (deck/model).
    document_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Source-of-truth pointer: which structured_answer or report this was generated from.
    source_report_id UUID REFERENCES reports(id) ON DELETE SET NULL,
    created_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_by    UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_artifacts_engagement ON artifacts(engagement_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_type      ON artifacts(engagement_id, type);
CREATE INDEX IF NOT EXISTS idx_artifacts_status    ON artifacts(status);
