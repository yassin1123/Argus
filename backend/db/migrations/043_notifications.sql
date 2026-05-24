-- Migration 043 — Phase 4 / Week 18 / Day 1: notification schema.
--
-- Two tables: ``notifications`` (the inbox) + ``notification_preferences``
-- (per-user per-type in_app/email flags). Both keyed by notification_type
-- string — the enum is intentionally CHECK-free so adding types later
-- doesn't require a constraint swap; the :class:`NotificationType`
-- enum in ``core.notifications.types`` is the single source of truth.
--
-- ``source_ref`` is a small JSONB — the SAME shape the W16 comments
-- table uses for anchor_ref. Keeps the W18 surface readable
-- ({comment_id} | {review_record_id} | {section_path} | {task_id}).
--
-- ``email_status`` tracks the lifecycle of the email-send side
-- (pending → sent | skipped | failed). Day 1 ships the dispatcher
-- that creates these rows with status pending/skipped; Day 3
-- ships the actual sender that flips them to sent/failed.

BEGIN;

CREATE TABLE IF NOT EXISTS notifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_id        UUID NOT NULL REFERENCES users(id),
    firm_id             UUID NOT NULL REFERENCES firms(id),
    notification_type   TEXT NOT NULL,
    session_id          UUID REFERENCES sessions(id) ON DELETE CASCADE,
    source_ref          JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_id            UUID REFERENCES users(id),
    summary             TEXT NOT NULL,
    read                BOOLEAN NOT NULL DEFAULT FALSE,
    read_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    email_status        TEXT NOT NULL DEFAULT 'pending',
    CONSTRAINT notifications_email_status_check CHECK (
        email_status IN ('pending', 'sent', 'skipped', 'failed')
    ),
    CONSTRAINT notifications_summary_nonempty CHECK (length(trim(summary)) > 0)
);

-- Inbox query hot path: "unread for me, newest first".
CREATE INDEX IF NOT EXISTS idx_notifications_recipient
    ON notifications(recipient_id, read, created_at DESC);
-- Engagement-scoped reads (e.g., "what just happened on Kestrel").
CREATE INDEX IF NOT EXISTS idx_notifications_session
    ON notifications(session_id);

CREATE TABLE IF NOT EXISTS notification_preferences (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    notification_type   TEXT NOT NULL,
    in_app              BOOLEAN NOT NULL DEFAULT TRUE,
    email               BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (user_id, notification_type)
);

COMMIT;
