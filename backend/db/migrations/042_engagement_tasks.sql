-- Migration 042 — Phase 4 / Week 17 / Day 3: lightweight explicit
-- engagement tasks.
--
-- Most "tasks" in Argus are DERIVED from existing signals (W15
-- change requests, W16 mentions, W17/D2 section assignments). This
-- table is the small explicit-task escape hatch for ad-hoc to-dos
-- that don't fit those rails — "ping the client lawyer", "double-
-- check the FX rate". Per the W17/D3 hard rule "don't build a full
-- project-management system": no subtasks, no dependencies, no
-- due-date columns. Just title + assignee + done.
--
-- ``done`` is a BOOLEAN rather than a status enum because there's
-- only one workflow direction here. ``done_at`` is set when the
-- transition happens so the audit trail is intact.
--
-- ``section_path`` is optional. When supplied, the workspace UI can
-- render the task inline with the section. When NULL, it's an
-- engagement-level to-do.

BEGIN;

CREATE TABLE IF NOT EXISTS engagement_tasks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    firm_id       UUID NOT NULL REFERENCES firms(id),
    title         TEXT NOT NULL,
    assigned_to   UUID REFERENCES users(id),
    created_by    UUID NOT NULL REFERENCES users(id),
    section_path  TEXT,
    done          BOOLEAN NOT NULL DEFAULT FALSE,
    done_at       TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT engagement_tasks_title_nonempty CHECK (length(trim(title)) > 0)
);

-- Open tasks for a user is the dashboard hot path; a partial index
-- keeps it tight even as the table grows.
CREATE INDEX IF NOT EXISTS idx_engagement_tasks_assignee_open
    ON engagement_tasks(assigned_to)
    WHERE done = FALSE;

-- "All tasks on this engagement" (used by the per-engagement task list).
CREATE INDEX IF NOT EXISTS idx_engagement_tasks_session
    ON engagement_tasks(session_id, created_at DESC);

COMMIT;
