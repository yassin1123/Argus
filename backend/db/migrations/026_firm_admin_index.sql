-- Phase 2 / Week 5 / Day 3 — partial admin index for firm_memberships.
--
-- The role column itself was already added in migration 024
-- (CHECK ('member', 'admin'), default 'member'). The Day 3 spec asked
-- for an additional column ALTER, which would be a no-op; we just need
-- the partial index that powers the "list firm admins" path.

CREATE INDEX IF NOT EXISTS idx_firm_memberships_admin
    ON firm_memberships(firm_id, role) WHERE role = 'admin';
