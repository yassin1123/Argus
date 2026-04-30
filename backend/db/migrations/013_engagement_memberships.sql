-- Phase 2: engagement-level permissions.
-- Owners get an automatic `lead` membership; others can be `member` or `viewer`.

CREATE TABLE IF NOT EXISTS engagement_memberships (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role          TEXT NOT NULL CHECK (role IN ('lead', 'member', 'viewer')),
    added_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (engagement_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_em_engagement ON engagement_memberships(engagement_id);
CREATE INDEX IF NOT EXISTS idx_em_user ON engagement_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_em_user_engagement ON engagement_memberships(user_id, engagement_id);

-- Backfill: every existing engagement with a creator gets that creator as `lead`.
INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
SELECT s.id, s.created_by_user_id, 'lead', s.created_by_user_id
FROM sessions s
WHERE s.created_by_user_id IS NOT NULL
ON CONFLICT (engagement_id, user_id) DO NOTHING;
