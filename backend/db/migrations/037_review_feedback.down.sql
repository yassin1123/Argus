-- Rollback for 037 — convert review_records.feedback back to TEXT.
--
-- The down-migration is lossy by design: structured pointers + per-pointer
-- resolution status flatten back to just the ``overall_note`` string.
-- This is the contract the down path advertises (the up-path's backfill
-- doc explains the shape); restoring the full structure would require a
-- shadow table.
--
-- The body is wrapped in a defensive guard so the file is a no-op when:
--   - review_records doesn't exist yet (fresh DB initialisation order
--     puts every .sql file in /docker-entrypoint-initdb.d through
--     alphabetically — .down.sql sorts before .sql so this file may
--     run before 036/037 up-migrations on a fresh boot);
--   - feedback is already TEXT (older operator already rolled back, or
--     never rolled forward).
-- Without the guard, the ``USING jsonb_typeof(feedback) ...`` clause
-- raises against a TEXT column and Postgres exits the initdb step
-- with code 3 — that's the CI failure this commit fixes.

-- Drop the W15/D3 GIN index unconditionally — IF EXISTS handles the
-- "doesn't exist yet" case during fresh-DB init ordering.
DROP INDEX IF EXISTS idx_review_records_feedback_path;

DO $$
BEGIN
    -- Only run the JSONB → TEXT conversion when the column is
    -- currently JSONB. On a fresh DB init, Postgres runs every .sql
    -- file in /docker-entrypoint-initdb.d alphabetically; this .down
    -- file sorts before 037_review_feedback.sql so it lands while
    -- feedback is still TEXT (from 036's default). The guard makes
    -- this file a no-op in that case so the init step doesn't fail
    -- (which produced exit-code-3 + CI failure on the prior shape).
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = 'review_records'
           AND column_name  = 'feedback'
           AND data_type    = 'jsonb'
    ) THEN
        ALTER TABLE review_records
            ALTER COLUMN feedback TYPE TEXT USING
                CASE
                    WHEN feedback IS NULL THEN NULL
                    WHEN jsonb_typeof(feedback) = 'object'
                         AND feedback ? 'overall_note'
                         THEN feedback ->> 'overall_note'
                    ELSE feedback::text
                END;
    END IF;
END
$$;
