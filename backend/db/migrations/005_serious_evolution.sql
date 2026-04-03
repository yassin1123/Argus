-- Pipeline UX, reasoning graph, claim-support table, consulting mode

ALTER TABLE sessions ADD COLUMN IF NOT EXISTS pipeline_state TEXT NOT NULL DEFAULT 'idle';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS report_mode TEXT NOT NULL DEFAULT 'general';

ALTER TABLE reports ADD COLUMN IF NOT EXISTS reasoning_graph JSONB DEFAULT '{}';
ALTER TABLE reports ADD COLUMN IF NOT EXISTS claim_support JSONB DEFAULT '[]';

CREATE TABLE IF NOT EXISTS claim_support_rows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    report_id UUID REFERENCES reports(id) ON DELETE CASCADE,
    claim_id TEXT NOT NULL,
    claim_text TEXT NOT NULL,
    evidence_object_ids UUID[] DEFAULT '{}',
    support_type TEXT NOT NULL DEFAULT 'inference',
    verifier_verdict TEXT,
    contradiction_flag BOOLEAN NOT NULL DEFAULT false,
    staleness_hint TEXT,
    entailment_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_claim_support_rows_session ON claim_support_rows(session_id);
CREATE INDEX IF NOT EXISTS idx_claim_support_rows_report ON claim_support_rows(report_id);
