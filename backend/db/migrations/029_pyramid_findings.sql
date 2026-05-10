-- Phase 2 / Week 8 / Day 1 — Pyramid Principle auto-checker.
--
-- Full check result lives in ``session.metadata.pyramid_check_result``
-- (JSONB on the existing ``sessions.metadata`` column). The migration
-- adds one materialised convenience column — ``pyramid_findings_count`` —
-- so dashboards can ``SELECT count(*) FROM sessions WHERE pyramid_findings_count > 0``
-- without unpacking JSONB on every query.
--
-- The column is advisory: it never blocks pipeline progression. NULL
-- means the check has not run for this session yet (e.g. legacy rows
-- from before W8).

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS pyramid_findings_count INTEGER;

CREATE INDEX IF NOT EXISTS idx_sessions_pyramid_findings_count
    ON sessions(pyramid_findings_count) WHERE pyramid_findings_count > 0;
