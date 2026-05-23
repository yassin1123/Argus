-- Rollback for 042.

BEGIN;

DROP TABLE IF EXISTS engagement_tasks;

COMMIT;
