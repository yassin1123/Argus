-- Migration 048 — Phase 5 / Week 23 / Day 3: firm-level cost governance.
--
-- Two columns on ``firms`` + one table tracking budget-threshold
-- notifications so the same threshold doesn't double-notify.
--
--   - ``monthly_budget_usd``        — the firm-wide monthly cap.
--                                     NULL = no cap (default;
--                                     firms opt-in).
--   - ``session_cost_ceiling_usd``  — the per-engagement backstop
--                                     (the W9/D4 deepening cap + the
--                                     "$5 ceiling" the W20/D3 spec
--                                     called out as aspirational).
--                                     Default $5.00 — applies to
--                                     every firm unless overridden.
--
-- ``firm_budget_notifications`` records which threshold the firm
-- has already been notified about in the current month so we
-- don't spam at every 80%+ check.

ALTER TABLE firms
    ADD COLUMN IF NOT EXISTS monthly_budget_usd DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS session_cost_ceiling_usd DOUBLE PRECISION
        NOT NULL DEFAULT 5.0;

CREATE TABLE IF NOT EXISTS firm_budget_notifications (
    id              BIGSERIAL PRIMARY KEY,
    firm_id         UUID NOT NULL,
    threshold_pct   INTEGER NOT NULL,
    -- 'YYYY-MM' bucket so the same threshold can re-fire in
    -- a new month.
    month_bucket    TEXT NOT NULL,
    notified_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, threshold_pct, month_bucket)
);

CREATE INDEX IF NOT EXISTS idx_firm_budget_notif_lookup
    ON firm_budget_notifications (firm_id, month_bucket);
