DROP INDEX IF EXISTS idx_firm_budget_notif_lookup;
DROP TABLE IF EXISTS firm_budget_notifications;
ALTER TABLE firms
    DROP COLUMN IF EXISTS session_cost_ceiling_usd,
    DROP COLUMN IF EXISTS monthly_budget_usd;
