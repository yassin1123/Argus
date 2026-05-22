-- Migration 036 — Phase 4 / Week 15 / Day 1: review workflow schema.
--
-- Adds:
--   * ``sessions.review_state`` — the lifecycle column the W15
--     state machine drives. Distinct from the existing
--     ``sessions.status`` (pipeline state: draft / processing /
--     deliverable_ready / ...) and from ``sessions.pipeline_state``
--     (orchestrator-internal). Naming chosen so the three never
--     collide.
--   * ``sessions.review_assigned_to`` — explicit reviewer
--     assignment. Optional; when null, any firm admin (or anyone
--     allow_self_approval permits) can approve. When set, the
--     authorisation layer additionally accepts the named member
--     even if they're not a firm admin.
--   * ``sessions.{approved_by, approved_at, submitted_at, submitted_by}``
--     — denormalised columns the workspace UI needs without paging
--     through the review_records audit table on every load.
--
-- New table ``review_records`` — append-only audit of every
-- transition. The state column on ``sessions`` is the current
-- truth; ``review_records`` is the history. Indexed on
-- (session_id, created_at DESC) so the workspace timeline view
-- pages cheaply.
--
-- ``firms.allow_self_approval`` defaults FALSE — segregation of
-- duties is the W15 spec's default. Solo / tiny firms flip it on
-- explicitly via firm-settings (UI lands in W17).

BEGIN;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS review_state TEXT NOT NULL DEFAULT 'draft',
    ADD COLUMN IF NOT EXISTS review_assigned_to UUID REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id),
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS submitted_by UUID REFERENCES users(id);

ALTER TABLE sessions
    DROP CONSTRAINT IF EXISTS sessions_review_state_check;
ALTER TABLE sessions
    ADD CONSTRAINT sessions_review_state_check CHECK (
        review_state IN ('draft', 'in_review', 'changes_requested', 'approved', 'delivered')
    );

CREATE TABLE IF NOT EXISTS review_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES firms(id),
    from_state      TEXT NOT NULL,
    to_state        TEXT NOT NULL,
    action          TEXT NOT NULL,
    actor_id        UUID NOT NULL REFERENCES users(id),
    reviewer_id     UUID REFERENCES users(id),
    feedback        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT review_records_action_check CHECK (
        action IN (
            'submit_for_review', 'approve', 'request_changes',
            'resubmit', 'mark_delivered', 'reopen', 'auto_revert'
        )
    ),
    CONSTRAINT review_records_from_state_check CHECK (
        from_state IN ('draft', 'in_review', 'changes_requested', 'approved', 'delivered')
    ),
    CONSTRAINT review_records_to_state_check CHECK (
        to_state IN ('draft', 'in_review', 'changes_requested', 'approved', 'delivered')
    )
);

CREATE INDEX IF NOT EXISTS idx_review_records_session
    ON review_records(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_records_firm_recent
    ON review_records(firm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_records_actor
    ON review_records(actor_id, created_at DESC);

ALTER TABLE firms
    ADD COLUMN IF NOT EXISTS allow_self_approval BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;
