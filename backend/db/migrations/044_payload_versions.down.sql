-- Rollback for 044.

BEGIN;

DROP TABLE IF EXISTS payload_versions;

COMMIT;
