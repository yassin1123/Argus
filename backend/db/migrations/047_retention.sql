-- Migration 047 — Phase 5 / Week 23 / Day 2: data retention + purge audit.
--
-- Two surfaces:
--
--   1. firms.retention_days — per-firm configurable retention
--      window (in days, measured from sessions.updated_at). NULL
--      = keep indefinitely (the safe default; firms opt-in).
--   2. purge_audit_log — append-only record of hard deletions.
--      Carries IDs + actor + counts; NEVER any client content.
--      Solves the "audit paradox": we record THAT a purge
--      happened without retaining the deleted data.
--   3. sessions.retention_flagged_at — when the retention sweep
--      flags an engagement past its window. The sweep notifies
--      the firm_admin + waits a grace period before actually
--      calling purge_engagement(). Nothing vanishes silently.

ALTER TABLE firms
    ADD COLUMN IF NOT EXISTS retention_days INTEGER;

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS retention_flagged_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retention_grace_expires_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS purge_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL,
    firm_id         UUID NOT NULL,
    actor_user_id   UUID,
    purge_reason    TEXT NOT NULL,          -- 'firm_admin_request' | 'retention_sweep'
    rows_deleted    JSONB NOT NULL DEFAULT '{}'::jsonb,
    files_deleted   INTEGER NOT NULL DEFAULT 0,
    purged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_purge_audit_firm_time
    ON purge_audit_log (firm_id, purged_at DESC);
CREATE INDEX IF NOT EXISTS idx_purge_audit_session
    ON purge_audit_log (session_id);
