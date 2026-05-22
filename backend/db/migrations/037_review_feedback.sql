-- Migration 037 — Phase 4 / Week 15 / Day 3.
--
-- Convert ``review_records.feedback`` from TEXT to JSONB so request-changes
-- transitions can store the structured ``ReviewFeedback`` shape (overall
-- note + per-section pointers + severity + per-pointer resolution
-- status). Backfills any existing plain-text feedback into the new
-- structured shape so the read path doesn't need a special case for
-- "old rows".
--
-- Structured shape (mirrors core/review/feedback.py):
--
--   {
--     "overall_note":      "<reviewer summary>",
--     "section_pointers":  [
--        { "section_path": "synergy_estimate",
--          "note": "Basis feels weak",
--          "severity": "major",
--          "resolved": false,
--          "resolved_at": null,
--          "resolved_by": null
--        }, ...
--     ],
--     "severity":          "minor" | "major" | "blocking"
--   }
--
-- Backfill policy: legacy plain-text feedback becomes ``overall_note``
-- with empty pointers + severity defaulted to ``major``. Major is the
-- safe default — the audit row reads "this was a substantive
-- request_changes round" without inventing a severity we can't justify.
--
-- Adds an index on the new JSONB column for the path-pointer queries
-- the resolve-pointer endpoint runs.

BEGIN;

ALTER TABLE review_records
    ALTER COLUMN feedback TYPE JSONB USING
        CASE
            WHEN feedback IS NULL THEN NULL
            -- Already-jsonb-shaped text (unlikely but tolerated) parses
            -- through; everything else gets wrapped.
            WHEN feedback LIKE '{%' THEN feedback::jsonb
            ELSE jsonb_build_object(
                'overall_note', feedback,
                'section_pointers', '[]'::jsonb,
                'severity', 'major'
            )
        END;

CREATE INDEX IF NOT EXISTS idx_review_records_feedback_path
    ON review_records USING gin ((feedback -> 'section_pointers'));

COMMIT;
