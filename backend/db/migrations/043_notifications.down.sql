-- Rollback for 043.

BEGIN;

DROP TABLE IF EXISTS notification_preferences;
DROP TABLE IF EXISTS notifications;

COMMIT;
