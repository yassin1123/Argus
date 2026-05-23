-- Rollback for 041 — drops the section_assignments table.

BEGIN;

DROP TABLE IF EXISTS section_assignments;

COMMIT;
