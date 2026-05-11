-- Phase 2 / Week 8 / Day 2 — MECE list-overlap auto-checker.
--
-- Full result lives in ``session.metadata.mece_check_result`` (JSONB
-- on the existing ``sessions.metadata`` column, alongside the Pyramid
-- result from migration 029). Adds one materialised count column for
-- cheap dashboard queries.
--
-- The column is advisory: it never blocks pipeline progression. NULL
-- means the check has not run for this session yet (legacy rows from
-- before W8).

ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS mece_overlaps_count INTEGER;

CREATE INDEX IF NOT EXISTS idx_sessions_mece_overlaps_count
    ON sessions(mece_overlaps_count) WHERE mece_overlaps_count > 0;
