-- Migration 038 — Phase 4 / Week 16 / Day 1: comment schema.
--
-- Threaded comments anchored to stable engagement targets. Reuses
-- the W9 section addressing (``synergy_estimate``,
-- ``frameworks.porters_five_forces``, ``risks[0]``) for SECTION
-- anchors and the W7+ claim_citations registry for CLAIM anchors.
-- TEXT_RANGE anchors are best-effort: they store the quoted text
-- so the W16/D1 orphan detector can flag a comment whose target
-- text has been deepened away. ARTIFACT anchors point at an
-- ``export_artifacts`` row (the W10–W13 deliverable bundle).
--
-- Threading: ``parent_comment_id`` NULL on root comments, set on
-- replies. Replies inherit the root's anchor — the service layer
-- enforces that contract; the schema doesn't store anchor on
-- replies (saves disk; root is one query away). Wait, looking at
-- the spec again: every comment row has anchor_type + anchor_ref
-- columns NOT NULL. Replies copy the root's anchor at insert
-- time. That's the simplest read path (no JOIN to discover anchor)
-- and the storage cost is trivial — one JSONB per row.
--
-- Soft delete: ``deleted_at`` NULL means "live". Per W16/D1 hard
-- rule no hard-deletes; audit trail integrity matters more than
-- the storage savings.
--
-- Resolution: thread-level only. ``resolved`` / ``resolved_by`` /
-- ``resolved_at`` are only meaningful on root comments. The
-- service layer rejects resolve calls on a non-root.

BEGIN;

CREATE TABLE IF NOT EXISTS comments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id             UUID NOT NULL REFERENCES firms(id),
    parent_comment_id   UUID REFERENCES comments(id) ON DELETE CASCADE,
    anchor_type         TEXT NOT NULL,
    anchor_ref          JSONB NOT NULL DEFAULT '{}'::jsonb,
    body                TEXT NOT NULL,
    mentioned_user_ids  JSONB NOT NULL DEFAULT '[]'::jsonb,
    author_id           UUID NOT NULL REFERENCES users(id),
    resolved            BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_by         UUID REFERENCES users(id),
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    edited_at           TIMESTAMPTZ,
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT comments_anchor_type_check CHECK (
        anchor_type IN ('engagement', 'section', 'claim', 'text_range', 'artifact')
    ),
    CONSTRAINT comments_body_nonempty CHECK (length(trim(body)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_comments_session
    ON comments(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_comments_thread
    ON comments(parent_comment_id);
CREATE INDEX IF NOT EXISTS idx_comments_anchor
    ON comments(session_id, anchor_type);
-- Author lookup for "my comments" surfaces in the workspace shell.
CREATE INDEX IF NOT EXISTS idx_comments_author
    ON comments(author_id, created_at DESC);

COMMIT;
