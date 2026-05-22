-- Rollback for 036 — restores the sessions / firms schema to its
-- pre-Phase-4 state. Drops the review_records audit table along
-- with its indexes + check constraints; removes the review_state
-- columns from sessions; drops allow_self_approval from firms.
--
-- Safe to run when no engagements are mid-review. Re-applying the
-- forward migration restores the default state ('draft') on every
-- existing session.

BEGIN;

DROP INDEX IF EXISTS idx_review_records_actor;
DROP INDEX IF EXISTS idx_review_records_firm_recent;
DROP INDEX IF EXISTS idx_review_records_session;
DROP TABLE IF EXISTS review_records;

ALTER TABLE sessions
    DROP CONSTRAINT IF EXISTS sessions_review_state_check;
ALTER TABLE sessions
    DROP COLUMN IF EXISTS submitted_by,
    DROP COLUMN IF EXISTS submitted_at,
    DROP COLUMN IF EXISTS approved_at,
    DROP COLUMN IF EXISTS approved_by,
    DROP COLUMN IF EXISTS review_assigned_to,
    DROP COLUMN IF EXISTS review_state;

ALTER TABLE firms
    DROP COLUMN IF EXISTS allow_self_approval;

COMMIT;
