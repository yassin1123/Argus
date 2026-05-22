-- Rollback for 038. Drops the comments table + its indexes.
-- Cascade through the FK chain handles any future tables that
-- end up referencing comments. All ``IF EXISTS`` guarded so the
-- file is safe to land before its paired ``038_comments.sql`` on
-- a fresh ``docker-entrypoint-initdb.d`` boot — the W15/D5 CI fix
-- documented that ordering trap; this migration follows the same
-- defensive pattern.

BEGIN;

DROP INDEX IF EXISTS idx_comments_author;
DROP INDEX IF EXISTS idx_comments_anchor;
DROP INDEX IF EXISTS idx_comments_thread;
DROP INDEX IF EXISTS idx_comments_session;
DROP TABLE IF EXISTS comments;

COMMIT;
