-- Migration 039 — Phase 4 / Week 16 / Day 4: GIN index on
-- comments.mentioned_user_ids.
--
-- The W16/D4 cross-engagement "my mentions" surface queries the
-- comments table for rows whose mentioned_user_ids JSONB array
-- contains a given user_id. Without an index this is a sequential
-- scan over every live comment row in the firm; with the JSONB GIN
-- it's an index lookup on the array.
--
-- ``jsonb_path_ops`` is intentional — it's about a third the size
-- of the default JSONB GIN opclass and only supports the @>
-- containment query we actually use ("does this array contain this
-- user_id"). We don't need the more general key-existence operators.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_comments_mentioned_user_ids
    ON comments USING GIN (mentioned_user_ids jsonb_path_ops);

COMMIT;
