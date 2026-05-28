-- Migration 049 — Phase 5 / Week 24 / Day 3: pilot feedback instrumentation.
--
-- The pilot's whole point is learning. Four lightweight, firm-scoped
-- surfaces capture what the consultants actually think of the output:
--
--   - claim_feedback           per-claim "is this verified correctly?"
--                              (one-click thumbs + optional note). Every
--                              row is a future training/labelling pair.
--   - artifact_ratings         per-deliverable quality rating on
--                              download/approve (thumb or 1-5 + comment).
--   - engagement_edit_telemetry  how much the consultant rewrote before
--                              approval — the killer signal. We store the
--                              FRACTION of edits + word/claim counts, NEVER
--                              the prose (the W20 privacy line).
--   - pilot_checkins           weekly structured check-in responses.
--
-- All four carry firm_id and are read back firm-scoped (W23 rule):
-- one firm's feedback is never visible to another.

CREATE TABLE IF NOT EXISTS claim_feedback (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES firms(id),
    -- The claim's id as it appears in the rendered payload. TEXT
    -- (not a FK) because claims live inside the JSONB payload, not a
    -- normalised table.
    claim_id        TEXT NOT NULL,
    -- The verification verdict shown to the consultant at the moment
    -- they gave feedback — frozen so a later re-verification doesn't
    -- rewrite history.
    verdict_at_feedback   TEXT,
    consultant_assessment TEXT NOT NULL CHECK (
        consultant_assessment IN
            ('correct', 'wrong_supported', 'wrong_flagged', 'unsure')
    ),
    note            TEXT,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_claim_feedback_firm
    ON claim_feedback (firm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_claim_feedback_session
    ON claim_feedback (session_id);
CREATE INDEX IF NOT EXISTS idx_claim_feedback_claim
    ON claim_feedback (claim_id);


CREATE TABLE IF NOT EXISTS artifact_ratings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES firms(id),
    artifact_id     UUID,
    artifact_type   TEXT,
    -- 1-5 stars (or 1/5 for a thumb down/up). Bounded so the average
    -- is meaningful.
    rating          INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment         TEXT,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_artifact_ratings_firm
    ON artifact_ratings (firm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_ratings_session
    ON artifact_ratings (session_id);


CREATE TABLE IF NOT EXISTS engagement_edit_telemetry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES firms(id),
    -- Word-level churn between the auto-generated (version 1) payload
    -- and the approved payload. Counts + a 0..1 fraction. NO prose.
    words_baseline  INTEGER NOT NULL DEFAULT 0,
    words_same      INTEGER NOT NULL DEFAULT 0,
    words_added     INTEGER NOT NULL DEFAULT 0,
    words_removed   INTEGER NOT NULL DEFAULT 0,
    edit_fraction   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    -- Structural claim churn.
    claims_baseline INTEGER NOT NULL DEFAULT 0,
    claims_added    INTEGER NOT NULL DEFAULT 0,
    claims_removed  INTEGER NOT NULL DEFAULT 0,
    approved_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One telemetry row per engagement (the approval moment). A
    -- re-approval after auto-revert refreshes it.
    UNIQUE (session_id)
);

CREATE INDEX IF NOT EXISTS idx_edit_telemetry_firm
    ON engagement_edit_telemetry (firm_id, created_at DESC);


CREATE TABLE IF NOT EXISTS pilot_checkins (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL REFERENCES firms(id),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    -- 'YYYY-Www' ISO week bucket so one check-in per firm per week is
    -- the natural grain (re-submitting in the same week updates).
    week_bucket     TEXT NOT NULL,
    responses       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, week_bucket)
);

CREATE INDEX IF NOT EXISTS idx_pilot_checkins_firm
    ON pilot_checkins (firm_id, week_bucket);
