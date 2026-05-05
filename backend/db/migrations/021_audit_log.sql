-- Phase 10: append-only audit log.
-- Every API call + every critical action lands here. Compliance teams will ask.
--
-- Production note: revoke UPDATE/DELETE from the application DB user so the
-- table is truly append-only. We don't do that in MVP (single shared user)
-- but the application code never issues UPDATE/DELETE against this table.

CREATE TABLE IF NOT EXISTS audit_events (
    id            BIGSERIAL PRIMARY KEY,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_email   TEXT,
    action        TEXT NOT NULL,           -- e.g. "session.create", "artifact.export", "auth.login"
    resource_type TEXT,                    -- e.g. "engagement", "artifact", "source"
    resource_id   TEXT,                    -- foreign-key value as text
    method        TEXT,                    -- HTTP method
    path          TEXT,                    -- request path
    status_code   INT,
    ip            TEXT,
    user_agent    TEXT,
    payload       JSONB DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_actor    ON audit_events(actor_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_resource ON audit_events(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_created  ON audit_events(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_action   ON audit_events(action);
