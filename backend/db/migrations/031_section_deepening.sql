-- Phase 2 / Week 9 / Day 1 — section deepening service.
--
-- One row per deepening request. The deepening is a SEPARATE
-- artifact from the original engagement's report: it doesn't modify
-- the source session payload in-place. The consultant decides later
-- (W9/D3 work) whether to merge a deepening's deepened_section_json
-- back into the parent report. This decouples "give me a deeper
-- look at section X" from "commit that deeper look into the memo."
--
-- ``status`` lifecycle: queued -> running -> complete | failed.
-- ``original_section_json`` is captured at request time so a later
-- merge can detect whether the parent section drifted in the
-- meantime (defensive vs concurrent edits).

CREATE TABLE IF NOT EXISTS section_deepening_runs (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id                UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id                   UUID NOT NULL REFERENCES firms(id),
    section_path              TEXT NOT NULL,         -- e.g. "synergy_estimate.cost_synergies"
    depth_directive           TEXT,                  -- consultant's freeform "make this deeper because..."
    triggered_by              UUID REFERENCES users(id),
    original_section_json     JSONB NOT NULL,
    deepened_section_json     JSONB,
    new_evidence_chunks_used  INTEGER DEFAULT 0,
    new_claim_ids             JSONB DEFAULT '[]'::jsonb,
    cost_usd                  DOUBLE PRECISION DEFAULT 0,
    wall_seconds              DOUBLE PRECISION DEFAULT 0,
    status                    TEXT NOT NULL DEFAULT 'queued',  -- queued | running | complete | failed
    failure_reason            TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_section_deepening_session
    ON section_deepening_runs(session_id, created_at DESC);
