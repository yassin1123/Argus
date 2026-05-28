-- Migration 050 — Phase 5 / Week 24 / Day 4: operator cost-burn alerts.
--
-- The W23 firm budget soft-stops NEW engagements at 100% and notifies
-- firm_admins at 80% / 100%. That protects the firm, but the OPERATOR
-- (Yassin) wants to see a firm approaching its cap BEFORE the soft-stop
-- fires, so a surprise stop never lands mid-pilot.
--
-- ops_cost_alerts is a tiny, cheap table the dashboard polls: one row
-- per (firm, month, level). A scan upserts the current level; the
-- dashboard reads active (unresolved, current-month) rows. No content —
-- just the firm + the spend numbers.

CREATE TABLE IF NOT EXISTS ops_cost_alerts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
    -- 'warn'   — used_pct in [WARN, 100)  : approaching the cap
    -- 'critical' — used_pct >= 100         : soft-stop active
    alert_level         TEXT NOT NULL CHECK (alert_level IN ('warn', 'critical')),
    used_pct            DOUBLE PRECISION NOT NULL,
    month_to_date_usd   DOUBLE PRECISION NOT NULL,
    monthly_budget_usd  DOUBLE PRECISION NOT NULL,
    month_bucket        TEXT NOT NULL,         -- 'YYYY-MM'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ,
    -- One live row per firm/month/level — the scan upserts it.
    UNIQUE (firm_id, month_bucket, alert_level)
);

CREATE INDEX IF NOT EXISTS idx_ops_cost_alerts_active
    ON ops_cost_alerts (month_bucket)
    WHERE resolved_at IS NULL;
