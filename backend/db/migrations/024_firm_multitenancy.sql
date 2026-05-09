-- Phase 2 / Week 5 / Day 1 — multi-tenancy backbone.
--
-- The pre-Phase-2 codebase was implicitly single-tenant: there is no `firms`
-- table, no `firm_id` columns, and `uploaded_files.scope='firm'` means
-- "visible across the whole deployment" rather than "isolated from another
-- firm's content". Phase 2 needs real cross-firm isolation as the firm-
-- knowledge layer ships, so this migration adds the tenancy backbone:
--
--   - firms                   (the tenant table)
--   - firm_memberships        (which users belong to which firm + role)
--   - users.default_firm_id   (a user's primary firm)
--   - chunks.firm_id          (which firm a chunk belongs to)
--   - sessions.firm_id        (which firm an engagement runs under)
--   - uploaded_files.firm_id  (which firm an upload belongs to)
--
-- All existing rows are backfilled into a single "Argus Default Firm"
-- (deterministic UUID 00000000-0000-0000-0000-000000000001) so the
-- NOT NULL constraints can be enforced. Every new firm is a fresh row
-- with its own UUID.
--
-- Roles in firm_memberships are kept open today (member | admin) but
-- enforcement of role-gated actions is Phase 2 / Day 3 work — today's
-- API code only checks membership, not role.

-- ---------------------------------------------------------------------------
-- 1. firms
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS firms (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,           -- url-safe identifier, e.g. "argus-default"
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata    JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_firms_slug ON firms(slug);

-- Deterministic default firm. Every row in the schema's existing tables gets
-- backfilled into this firm below.
INSERT INTO firms (id, name, slug)
VALUES ('00000000-0000-0000-0000-000000000001', 'Argus Default Firm', 'argus-default')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. firm_memberships
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS firm_memberships (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'admin')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_firm_memberships_user ON firm_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_firm_memberships_firm ON firm_memberships(firm_id);

-- Backfill: every existing user becomes a member of the default firm.
INSERT INTO firm_memberships (firm_id, user_id, role)
SELECT
    '00000000-0000-0000-0000-000000000001',
    u.id,
    CASE WHEN u.role = 'admin' THEN 'admin' ELSE 'member' END
FROM users u
WHERE NOT EXISTS (
    SELECT 1 FROM firm_memberships m
    WHERE m.user_id = u.id
      AND m.firm_id = '00000000-0000-0000-0000-000000000001'
);

-- ---------------------------------------------------------------------------
-- 3. users.default_firm_id
-- ---------------------------------------------------------------------------

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS default_firm_id UUID REFERENCES firms(id) ON DELETE SET NULL;

UPDATE users
SET default_firm_id = '00000000-0000-0000-0000-000000000001'
WHERE default_firm_id IS NULL;

-- ---------------------------------------------------------------------------
-- 4. firm_id on the data tables
-- ---------------------------------------------------------------------------

-- sessions.firm_id (was created_by_user_id at most)
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id) ON DELETE RESTRICT;

UPDATE sessions
SET firm_id = COALESCE(
    (SELECT u.default_firm_id FROM users u WHERE u.id = sessions.created_by_user_id),
    '00000000-0000-0000-0000-000000000001'
)
WHERE firm_id IS NULL;

ALTER TABLE sessions
    ALTER COLUMN firm_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_firm ON sessions(firm_id);

-- uploaded_files.firm_id (already has scope='firm', this is the tenancy layer)
ALTER TABLE uploaded_files
    ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id) ON DELETE RESTRICT;

UPDATE uploaded_files
SET firm_id = COALESCE(
    (SELECT s.firm_id FROM sessions s WHERE s.id = uploaded_files.session_id),
    '00000000-0000-0000-0000-000000000001'
)
WHERE firm_id IS NULL;

ALTER TABLE uploaded_files
    ALTER COLUMN firm_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_uploaded_files_firm ON uploaded_files(firm_id);

-- chunks.firm_id (the load-bearing column for retrieval-time isolation).
-- chunks.session_id is nullable since migration 023 (firm-global SEC chunks),
-- so we backfill firm_id from session when present, else default.
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id) ON DELETE RESTRICT;

UPDATE chunks
SET firm_id = COALESCE(
    (SELECT s.firm_id FROM sessions s WHERE s.id = chunks.session_id),
    '00000000-0000-0000-0000-000000000001'
)
WHERE firm_id IS NULL;

ALTER TABLE chunks
    ALTER COLUMN firm_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_firm ON chunks(firm_id);
CREATE INDEX IF NOT EXISTS idx_chunks_firm_source_type ON chunks(firm_id, source_type);
