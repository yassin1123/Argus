-- Migration 045 — Phase 5 / Week 20 / Day 2: metric events.
--
-- One row per recorded metric sample. Lightweight and append-only —
-- pilot-scale volume (low-hundreds of engagements/day) is comfortably
-- served by raw events; rollup tables can land later (W22+) if the
-- query layer starts feeling the heat.
--
-- Index strategy:
--   - (metric_name, recorded_at DESC) — the dominant query pattern is
--     "what did <metric> do over the last N minutes", optionally
--     grouped by a label
--   - (firm_id, recorded_at DESC) — per-firm scoping for the
--     /api/admin/metrics endpoint when called by a firm_admin
--
-- Labels live in a JSONB blob rather than columns so adding a new
-- label dimension doesn't require a migration. Hot dimensions
-- (firm_id, trace_id) are promoted to top-level columns for cheap
-- filtering + the firm-scoping index.

CREATE TABLE IF NOT EXISTS metric_events (
    id           BIGSERIAL PRIMARY KEY,
    metric_name  TEXT NOT NULL,
    labels       JSONB NOT NULL DEFAULT '{}'::jsonb,
    value        DOUBLE PRECISION NOT NULL,
    trace_id     UUID,
    firm_id      UUID,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_metric_events_name_time
    ON metric_events (metric_name, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_metric_events_firm
    ON metric_events (firm_id, recorded_at DESC)
    WHERE firm_id IS NOT NULL;
