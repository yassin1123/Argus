-- Phase 2 / Week 9 / Day 3 — accept/reject + history-preserving snapshot.
--
-- The W9/D1 ``section_deepening_runs`` row already captures the
-- section's pre-state in ``original_section_json``. To preserve the
-- BROADER memo history when an accept lands, we also snapshot the
-- full pre-accept ``reports`` payload onto the deepening row at
-- accept time. That keeps a single ``reports`` row per session
-- (existing UNIQUE(session_id) constraint preserved — no breaking
-- change to readers) while leaving an auditable rollback path.
--
-- Idempotency: a second accept on the same deepening is a no-op
-- because ``accepted_at`` is already set. The acceptance service
-- short-circuits on the non-NULL check.

ALTER TABLE section_deepening_runs
    ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS accepted_by UUID REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS rejected_by UUID REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS pre_accept_payload_snapshot JSONB;

-- Partial index for the common "accepted-but-not-rolled-back" query.
CREATE INDEX IF NOT EXISTS idx_section_deepening_accepted
    ON section_deepening_runs(session_id, accepted_at DESC)
    WHERE accepted_at IS NOT NULL;
