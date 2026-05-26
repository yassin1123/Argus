-- Down: drop the cost_ledger table + its indexes.
DROP INDEX IF EXISTS idx_cost_ledger_firm_time;
DROP INDEX IF EXISTS idx_cost_ledger_session;
DROP TABLE IF EXISTS cost_ledger;
