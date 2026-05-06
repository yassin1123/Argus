# Hard benchmark fixture — planted overstatements

Phase 1 / Week 2 / Day 4. Five hand-edited claims grafted onto a known-good
Week 1 NEW analyst output (`backend/eval_runs/week1_benchmark/new/run_1.json`,
gitignored), each introducing a specific factual overstatement that the
verification ensemble should catch but a gist-anchored LLM judge often
misses.

The runner at `tools/run_week2_hard_benchmark.py` consumes these fixtures
plus the seeded evidence catalogue in
`backend/tests/fixtures/germany_vs_france/evidence.json` (10 evidence rows,
1:1 mapped to the 10 analyst key_claims) and exercises the verification
stage under three configs: `llm_only`, `llm_plus_deberta`, `full_ensemble`.

## Files

- `analyst_output.json` — the full analyst output JSON. Five claims have
  edits applied; the remaining five are unchanged. Every `key_claim`'s
  `evidence_ids` are re-keyed from the per-run UUIDs in `run_1.json` to
  the deterministic fixture UUIDs (`e0000001-…-e0000010`) so the fixture
  is self-contained — runs against any database / fresh container.
- `planted_overstatements.json` — ledger of the five edits, each entry:
  `{claim_id, edit_type, original_text, edited_text, expected_min_verdict}`.

## Five planted edits

Every edit replaces a single specific factual element while leaving the
surrounding structure of the claim intact, so the LLM judge cannot
trivially detect the planted claim by its prose.

1. **Numeric inflation** — `market_size_germany`
   `€18.4B → €27.6B` (+50% on the German B2B SaaS market size).
   Why: the lexical-overlap MONEY signal should fire (€27.6B is not
   in the cited chunk; ±2% tolerance is well exceeded). DeBERTa
   should at minimum drop entailment confidence; ideally flips to
   neutral or contradiction because €27.6B is roughly 50% larger
   than the cited €18.4B.

2. **Percentage swap** — `france_growth_rate`
   `grew 22% year-over-year → grew 55% year-over-year` (+33 percentage
   points on France's B2B SaaS growth rate). The lexical PERCENT
   signal should fire (cited chunk says 22%; ±0.1pp tolerance is way
   off). DeBERTa is most likely to neutral here since the chunk
   explicitly states 22%.

3. **Region/entity swap** — `geographic_concentration`
   `North Rhine-Westphalia and Bavaria → Berlin and Hamburg`. Same
   GPE type (German states / cities). The lexical entity signal
   should fire — Berlin and Hamburg do not appear in the cited chunk;
   NRW and Bavaria do. DeBERTa is most likely to neutral or
   contradiction.

4. **Headcount inflation** — `team_cost_differential`
   `6-person GTM team → 20-person GTM team` (3.3×). The cited chunk
   discusses a 6-person team; the cardinal "20" doesn't appear.
   Lexical CARDINAL signal should fire. DeBERTa is most likely to
   neutral or contradiction (the financial figures in the same claim
   reference the 6-person numbers).

5. **Date shift** — `france_public_sector`
   `in public-sector SaaS purchases in 2024 → in public-sector SaaS
   purchases in 2026` (+2 years). Lexical DATE_YEAR signal should
   fire (chunk says 2024). DeBERTa likely neutral.

`expected_min_verdict` for all five is `"weak"` — i.e. the ensemble
must downgrade each from `supported` to at least `weak`,
`unsupported`, or `contradicted`. The exact category isn't fixed
because the operative criterion is "did the verifier flag it as
not fully supported?", not which weak-class label it landed on.

## Why these specific patterns

The five edit types correspond to the five precision failure modes
the wedge is supposed to surface. A LLM judge anchored on gist often
ratifies all five — the surrounding prose still reads like a sound
finding from the source. The lexical signal catches each because the
specific value the claim asserts no longer matches the cited chunk;
DeBERTa (whose training distribution is heavy on factual entailment)
catches the larger ones via "neutral" or "contradiction" labels.

## Why not edit more than five

Statistical power past 5 isn't worth the engineering time on a
hand-built fixture (per the Day 4 spec hard rule). A ≥4-of-5
ensemble recall vs ≤1-of-5 LLM-only recall is unambiguous enough
to call the wedge real.

## What's intentionally NOT planted

- No edits to `procurement_cycles`, `data_residency_requirements`,
  `sequenced_entry_advantage`, `nrr_comparison`, or
  `pilot_program_accuracy`. Those five act as the **unplanted
  control set** so the runner can compute precision and a false-flag
  rate (i.e. how many unplanted claims the verifier wrongly flags).
- No edits introducing claims that are arguably correct (e.g.
  loosening a number rather than tightening it). The planted set
  is unambiguously wrong relative to the evidence.
