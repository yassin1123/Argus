-- Rollback for 022_ensemble_verdicts.sql. Drops the index first so the
-- column drops don't trip a dependency error, then drops every column.
-- IF EXISTS guards make repeat runs harmless.

DROP INDEX IF EXISTS idx_claim_support_ensemble;

ALTER TABLE claim_support_rows
  DROP COLUMN IF EXISTS nli_label,
  DROP COLUMN IF EXISTS nli_confidence,
  DROP COLUMN IF EXISTS numeric_overlap_score,
  DROP COLUMN IF EXISTS numeric_overlap_missing,
  DROP COLUMN IF EXISTS entity_overlap_score,
  DROP COLUMN IF EXISTS entity_overlap_missing,
  DROP COLUMN IF EXISTS ensemble_verdict,
  DROP COLUMN IF EXISTS ensemble_reason;
