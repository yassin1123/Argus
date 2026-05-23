-- Rollback for 040 — restore the legacy 3-value role CHECK +
-- collapse the W17 role vocabulary back to member/viewer.
--
-- Lossy by design: ``reviewer`` is a W17 concept with no clean
-- pre-W17 analogue. We map reviewer → member (which retains
-- read+write capability) so the W15 review_assigned_to alignment
-- doesn't break, but the explicit "this is the assigned reviewer"
-- distinction is lost. The down path advertises this — operators
-- rolling back should expect the workspace UI to lose the
-- reviewer-badge surface.
--
-- The body is guarded so this file is a no-op when the
-- legacy CHECK is already in place (fresh DB initialisation
-- runs all .sql alphabetically; .down sorts before .sql so this
-- file may run before 040 up on a fresh boot).

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = 'engagement_memberships'
           AND column_name  = 'removed_at'
    ) THEN
        -- Collapse W17 roles back to the legacy 3-value vocabulary.
        UPDATE engagement_memberships SET role = 'member' WHERE role = 'contributor';
        UPDATE engagement_memberships SET role = 'member' WHERE role = 'reviewer';
        UPDATE engagement_memberships SET role = 'viewer' WHERE role = 'observer';

        ALTER TABLE engagement_memberships
            DROP CONSTRAINT IF EXISTS engagement_memberships_role_check;
        ALTER TABLE engagement_memberships
            ADD CONSTRAINT engagement_memberships_role_check
            CHECK (role IN ('lead', 'member', 'viewer'));

        DROP INDEX IF EXISTS idx_em_engagement_active;
        DROP INDEX IF EXISTS idx_em_user_active;

        ALTER TABLE engagement_memberships
            DROP COLUMN IF EXISTS removed_at;
    END IF;
END
$$;

COMMIT;
