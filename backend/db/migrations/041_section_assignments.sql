-- Migration 041 — Phase 4 / Week 17 / Day 2: per-section
-- ownership + work-status tracking.
--
-- One row per (session_id, section_path). Unique constraint
-- enforces "one owner at a time" — re-assigning overwrites via
-- UPSERT in the service. ``firm_id`` is denormalised from
-- sessions for cheaper firm-scoped queries (matches the W16
-- comments table pattern).
--
-- Status enum is enforced by CHECK rather than Postgres ENUM so
-- adding values later (e.g. 'blocked' if user demand emerges)
-- is a CHECK constraint swap, not a type migration.
--
-- Distinct from the W15 sessions.review_state — section_status
-- is granular per-section work tracking; review_state is the
-- formal engagement-level gate. The two never share a column.

BEGIN;

CREATE TABLE IF NOT EXISTS section_assignments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES firms(id),
    section_path    TEXT NOT NULL,
    assigned_to     UUID REFERENCES users(id),
    assigned_by     UUID REFERENCES users(id),
    status          TEXT NOT NULL DEFAULT 'not_started',
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT section_assignments_status_check CHECK (
        status IN ('not_started', 'in_progress', 'needs_review', 'done')
    ),
    UNIQUE (session_id, section_path)
);

CREATE INDEX IF NOT EXISTS idx_section_assignments_session
    ON section_assignments(session_id);
CREATE INDEX IF NOT EXISTS idx_section_assignments_owner
    ON section_assignments(assigned_to)
    WHERE assigned_to IS NOT NULL;

COMMIT;
