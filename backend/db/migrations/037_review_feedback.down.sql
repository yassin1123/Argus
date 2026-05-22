-- Rollback for 037 — convert review_records.feedback back to TEXT.
--
-- The down-migration is lossy by design: structured pointers + per-pointer
-- resolution status flatten back to just the ``overall_note`` string.
-- This is the contract the down path advertises (the up-path's backfill
-- doc explains the shape); restoring the full structure would require a
-- shadow table.

BEGIN;

DROP INDEX IF EXISTS idx_review_records_feedback_path;

ALTER TABLE review_records
    ALTER COLUMN feedback TYPE TEXT USING
        CASE
            WHEN feedback IS NULL THEN NULL
            WHEN jsonb_typeof(feedback) = 'object'
                 AND feedback ? 'overall_note'
                 THEN feedback ->> 'overall_note'
            ELSE feedback::text
        END;

COMMIT;
