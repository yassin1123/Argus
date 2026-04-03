-- V2: normalized citeable evidence, claim links, deck blueprints, evaluations, report verification.

CREATE TABLE IF NOT EXISTS evidence_objects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    task_id INTEGER,
    claim TEXT NOT NULL DEFAULT '',
    quote TEXT NOT NULL DEFAULT '',
    source_title TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_date TEXT,
    source_type TEXT NOT NULL DEFAULT 'web',
    source_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    confidence TEXT NOT NULL DEFAULT 'medium',
    is_inference BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_objects_session ON evidence_objects(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_objects_task ON evidence_objects(session_id, task_id);

CREATE TABLE IF NOT EXISTS claim_evidence_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    claim_ref TEXT NOT NULL DEFAULT '',
    evidence_object_id UUID NOT NULL REFERENCES evidence_objects(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL DEFAULT 'supports',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_claim_evidence_links_report ON claim_evidence_links(report_id);

CREATE TABLE IF NOT EXISTS deck_blueprints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    blueprint JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_deck_blueprints_session ON deck_blueprints(session_id);

CREATE TABLE IF NOT EXISTS evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    metrics JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evaluations_session ON evaluations(session_id);

ALTER TABLE reports ADD COLUMN IF NOT EXISTS verification JSONB DEFAULT '{}';
ALTER TABLE reports ADD COLUMN IF NOT EXISTS evidence_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reports ADD COLUMN IF NOT EXISTS unsupported_claim_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS gap_report JSONB DEFAULT '{}';
