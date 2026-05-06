-- Phase 1 / Week 2 / Day 3 — three-signal ensemble verdict columns.
--
-- Each claim_support_row now carries the raw outputs of the three
-- verifier signals (LLM judge, DeBERTa NLI, lexical overlap) plus the
-- aggregated `ensemble_verdict` produced by core/nli/aggregator.py.
-- The legacy `verifier_verdict` and `entailment_score` columns stay
-- populated for backward compatibility — the writer/critic/contradiction
-- gates read either the legacy or ensemble verdict based on the
-- ARGUS_USE_ENSEMBLE_VERDICT feature flag.
--
-- Spec wanted file 006_ensemble_verdicts.sql but 006 is taken
-- (006_claim_support_weak_flag.sql); next free is 022.

ALTER TABLE claim_support_rows
  ADD COLUMN IF NOT EXISTS nli_label TEXT,
  ADD COLUMN IF NOT EXISTS nli_confidence DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS numeric_overlap_score DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS numeric_overlap_missing JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS entity_overlap_score DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS entity_overlap_missing JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS ensemble_verdict TEXT,
  ADD COLUMN IF NOT EXISTS ensemble_reason TEXT;

CREATE INDEX IF NOT EXISTS idx_claim_support_ensemble
  ON claim_support_rows(ensemble_verdict)
  WHERE ensemble_verdict IS NOT NULL;
