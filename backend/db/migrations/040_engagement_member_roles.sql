-- Migration 040 — Phase 4 / Week 17 / Day 1: engagement membership
-- + assignment schema.
--
-- W17 introduces explicit collaboration roles on top of the
-- engagement_memberships table that's been live since W2/W3. Three
-- changes:
--
--   1. Expand the role CHECK to allow the W17 vocabulary:
--      lead | contributor | reviewer | observer. The pre-W17 values
--      member / viewer are mapped to contributor / observer on
--      this migration (no data loss — they're synonyms).
--
--   2. Add ``removed_at TIMESTAMPTZ`` for soft-remove. Per W17/D1
--      hard rule "no hard deletes; soft remove preserves audit
--      integrity". Existing rows get NULL (= live).
--
--   3. Backfill leads — every session must have exactly one lead per
--      W17/D1 invariant. We use sessions.created_by_user_id as the
--      author of record. Sessions whose creator is NULL (rare; older
--      seeds) are left without a backfilled lead and the W17 service
--      will surface them as warnings.
--
-- The existing column names (``added_by``, ``added_at``) stay — the
-- spec's ``assigned_by`` / ``assigned_at`` are aliases at the
-- service-layer dataclass. Renaming the columns would break every
-- pre-W17 caller (auth.permissions, review.service, comments
-- service) for no observable benefit. Spec asks for semantics, not
-- column naming.
--
-- The W9 deepening + W15 review pipelines read from
-- :func:`auth.permissions.get_engagement_role` which now also
-- accepts the new role tokens (mapped via _CAPABILITY_FOR_ROLE).

BEGIN;

-- 1. Drop the legacy 3-value CHECK, install the W17 4-value CHECK.
ALTER TABLE engagement_memberships
    DROP CONSTRAINT IF EXISTS engagement_memberships_role_check;

-- Map legacy roles before re-installing the CHECK so the
-- ALTER doesn't fight existing data.
UPDATE engagement_memberships SET role = 'contributor' WHERE role = 'member';
UPDATE engagement_memberships SET role = 'observer'    WHERE role = 'viewer';

ALTER TABLE engagement_memberships
    ADD CONSTRAINT engagement_memberships_role_check
    CHECK (role IN ('lead', 'contributor', 'reviewer', 'observer'));

-- 2. Soft-remove column.
ALTER TABLE engagement_memberships
    ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ;

-- 3. Active-only index so the soft-remove query stays cheap.
--    Existing ``idx_em_engagement`` is full-table; we add a
--    partial-on-active without dropping the legacy one (legacy
--    callers that don't filter on ``removed_at`` still benefit).
CREATE INDEX IF NOT EXISTS idx_em_engagement_active
    ON engagement_memberships(engagement_id)
    WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_em_user_active
    ON engagement_memberships(user_id)
    WHERE removed_at IS NULL;

-- 4. Backfill leads — every session with a created_by_user_id gets
--    a lead row. ON CONFLICT promotes any existing membership to
--    lead so a session that already had its creator as a
--    contributor / viewer ends up with them as lead (the W17
--    invariant: exactly one lead per engagement).
INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
SELECT s.id, s.created_by_user_id, 'lead', s.created_by_user_id
  FROM sessions s
 WHERE s.created_by_user_id IS NOT NULL
   AND NOT EXISTS (
       SELECT 1 FROM engagement_memberships em
        WHERE em.engagement_id = s.id
          AND em.role = 'lead'
          AND em.removed_at IS NULL
   )
ON CONFLICT (engagement_id, user_id) DO UPDATE
  SET role = 'lead',
      removed_at = NULL;

COMMIT;
