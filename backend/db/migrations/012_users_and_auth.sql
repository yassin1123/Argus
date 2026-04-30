-- Phase 1: email/password auth.
-- users + auth sessions; sessions table gets a created_by_user_id.

-- Allow case-insensitive email comparisons.
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         CITEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'member',  -- member | admin (firm-wide)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

-- sessions_auth = web auth sessions (cookie-backed). Renamed to avoid
-- colliding with the engagement `sessions` table.
CREATE TABLE IF NOT EXISTS sessions_auth (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,           -- sha256 of opaque token
    issued_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL,
    ip          TEXT,
    user_agent  TEXT,
    revoked_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sessions_auth_user ON sessions_auth(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_auth_expires ON sessions_auth(expires_at);

-- Engagement ownership. Phase 2 will add the memberships table for sharing.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_sessions_created_by ON sessions(created_by_user_id);
