-- Rollback for 039.

BEGIN;

DROP INDEX IF EXISTS idx_comments_mentioned_user_ids;

COMMIT;
