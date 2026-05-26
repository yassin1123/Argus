-- Migration 046 — Phase 5 / Week 20 / Day 3: cost ledger.
--
-- Phase 7's `llm_calls` table records per-call cost with full
-- attribution to session + user + task_kind + model + provider.
-- The W20/D3 ledger does NOT replace it — it's a parallel,
-- denormalised view optimised for the billing/budget question
-- "how much has this engagement / firm cost." Same data; different
-- index shape; explicit firm_id + trace_id columns so:
--
--   - the per-firm cost rollup query doesn't have to join through
--     sessions to resolve firm scope
--   - the W20/D1 trace_id ties a call back to its request lifecycle
--
-- `llm_calls` remains the authoritative per-call audit row. The
-- ledger is the authoritative source for cost rollups + the
-- session-cost-total used by the per-run cost gates.
--
-- Index strategy:
--   - (session_id)               — engagement_cost() lookup
--   - (firm_id, recorded_at DESC) — firm_cost() time-windowed lookup

CREATE TABLE IF NOT EXISTS cost_ledger (
    id                BIGSERIAL PRIMARY KEY,
    trace_id          UUID,
    session_id        UUID REFERENCES sessions(id) ON DELETE SET NULL,
    firm_id           UUID NOT NULL,
    agent             TEXT NOT NULL,
    provider          TEXT NOT NULL,
    model             TEXT NOT NULL,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd          DOUBLE PRECISION NOT NULL,
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cost_ledger_session
    ON cost_ledger (session_id);

CREATE INDEX IF NOT EXISTS idx_cost_ledger_firm_time
    ON cost_ledger (firm_id, recorded_at DESC);
