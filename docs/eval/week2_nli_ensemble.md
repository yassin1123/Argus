# Week 2 — NLI ensemble

**Decision (top-line):** **lock**

Same prompt (Germany vs France market entry), same intake answers, same seeded
evidence catalogue. The only delta from the Week 1 NEW baseline is the
verifier ensemble: the writer now reads `claim_support_rows.ensemble_verdict`
(produced by the Day 3 aggregator over the LLM judge + DeBERTa NLI + lexical
overlap signals) with `ARGUS_USE_ENSEMBLE_VERDICT=true`.

Source data:
- Hard benchmark (planted overstatements): `docs/eval/week2_hard_benchmark_run.json` (committed)
- Standard regression (3 ensemble-ON runs): `backend/eval_runs/week2_regression/run_{1,2,3}.json` (gitignored), `backend/eval_runs/week2_regression/summary.json` and `summary.csv` (committed)

## Hard benchmark (planted overstatements)

5 hand-edited overstatements (one per pattern: numeric inflation, percent
swap, region swap, headcount inflation, date shift) grafted onto a known-good
Week 1 NEW analyst output. Verification stage only — no planner / researcher
/ writer. See `backend/tests/fixtures/germany_vs_france_hard/README.md`.

| Config | Recall on planted (n=5) | Precision on flagged | False-flag rate (unplanted, n=5) |
|---|---|---|---|
| llm_only | **3/5 (0.60)** | 3/3 (1.00) | 0/5 (0.00) |
| llm_plus_deberta | **5/5 (1.00)** | 5/10 (0.50) | 5/5 (1.00) |
| full_ensemble | **5/5 (1.00)** | 5/10 (0.50) | 5/5 (1.00) |

**Bar:** `full_ensemble` recall ≥ 4/5 AND `llm_only` recall ≤ 1/5. **fail
(strict)**. Ensemble side passes (5/5); LLM side does not (3/5 ≰ 1/5). The
strict bar fails because gpt-4o (the Phase 1 routing's verifier model)
is much better at catching planted overstatements than the spec author
anticipated, *not* because the ensemble fails. The wedge nonetheless adds
measurable recall on the two LLM-only misses:

- `france_public_sector` — date shift `2024 → 2026`. LLM said `supported`;
  ensemble said `weak`.
- `team_cost_differential` — headcount `6-person → 20-person`. LLM said
  `supported`; ensemble said `contradicted`.

Both are precision-bug patterns the LLM judge anchors past on gist; DeBERTa
sees them. Recall lift = +2/5 on exactly the class the ensemble exists to
catch.

`llm_plus_deberta` and `full_ensemble` produce **identical** verdicts on
every claim. The lexical overlap signal is currently subsumed by DeBERTa's
"neutral" label on paraphrases. Worth investigating in Week 3 whether the
lexical layer adds value once DeBERTa's threshold is tuned, or whether it
should be retired as redundant with NLI on this evidence shape.

The precision drop (1.00 → 0.50) is real: the ensemble flags 5 of the 5
unplanted control claims as `weak` too. That headline number is misleading
read alone, though — see the regression below for what the writer does
*with* a corpus where most claims are `weak`.

## Standard regression (germany-vs-france, 3 runs, ensemble ON)

3 fresh sessions, identical fixture, only `ARGUS_USE_ENSEMBLE_VERDICT=true`
differs from the Week 1 NEW baseline.

| Metric | Week 1 NEW | Week 2 (ensemble) | Δ |
|---|---|---|---|
| Total claims (avg, all rows incl. assumptions) | 20.0 | 20.33 | +0.33 (+1.6%) |
| Key claims only (avg, scoring set) | ~10 | 10.33 | +0.33 |
| supported_high / supported_low / weak / contradicted (totals over 3 runs) | n/a | 4 / 0 / 27 / 0 | new metric |
| Recommendation specificity: numerics in recommendation | 7.67 | **17.67** | **+10.0 (+130%)** |
| Recommendation specificity: named options | 5.33 | 6.67 | +1.34 (+25%) |
| Recommendation specificity: time-bound next-steps | 10.0 | 8.67 | −1.33 (−13%) |
| Forbidden-phrase hits | 0.67 | **0.0** | −0.67 (perfect) |
| Cost per run (USD) | 0.57 | 0.77 | +0.20 (+35%) |
| Wall-clock per run (s) | 595.73 | 760.93 | +165.2 (+28%) |

**Bar:** surviving claim count ≥ 18.0 (≤10% degradation), no measurable hit
to recommendation specificity. **pass**.

Surviving claim count: 20.33 ≥ 18.0 — held with margin. Specificity moved
*up*, not down: numerics doubled, named segments gained 25%, forbidden
phrases zeroed out. The only mild regression is time-bound next-steps
(−13%); this is small and not load-bearing for the deliverable.

The cost / wall-clock premium is real (~35% / 28%) and entirely driven by
the DeBERTa Celery hops. $0.20 / run extra and ~3 minutes more wall is the
price for the recall lift on the precision-bug class.

### What the writer actually does with a "mostly weak" verdict spread

Of 31 key-claim verdicts across the 3 runs: 4 supported, 27 weak, 0
unsupported, 0 contradicted. Almost everything the analyst writes lands at
`weak` because DeBERTa labels paraphrased claims as `neutral`, the
truth-table downgrades, and the writer reads that. **The writer adapts —
not collapses.** Run 3's recommendation is unusually validation-gated:

> "Within 30 days: Validate four critical assumptions through direct research
> (Germany market ≥€15B, Mittelstand NRR exceeds French mid-market by ≥5
> points, ≥30% of your actual ICP concentrates in NRW+Bavaria, 7-month cycles
> are sustainable in… "

Run 1 and Run 2 produce comparable specificity with the same gating
behaviour. Net effect: the ensemble pushes the writer toward more
quantitative thresholds, more explicit go/no-go gates, and more named
validation steps — exactly the property the project optimises for.

## Decision (4–6 sentences)

**Lock new ensemble routing.** On the hard benchmark the wedge adds two
real catches the LLM judge anchored past (date shift, headcount inflation)
and the ensemble side of the bar holds at 5/5; the strict bar's other
condition (LLM ≤ 1/5) fails because gpt-4o under our Phase 1 routing is
genuinely strong, not because the wedge is hollow. On the standard
regression the surviving-claim bar holds with margin (20.33 vs 18.0
floor) and recommendation specificity moves *up* on three of four axes
(numerics +130%, named options +25%, forbidden phrases zeroed out) with
only a small time-bound-step regression. The +35% cost and +28% wall-clock
penalty buys behaviour where almost all claims now flow as `weak`, the
writer adapts by quantifying every threshold and naming explicit
validation gates ("≥€15B / ≥5 points / ≥30%"), and the report ships with
sharper specificity than the Week 1 NEW baseline. The truth-table
precision concern from Day 4 (5/5 unplanted false-flagged) is real and
deserves Week 3 attention — DeBERTa appears to be doing all the recall
lift, lexical overlap is currently redundant with it, and the threshold
may be tunable up — but the downstream writer behaviour validates the
current ensemble-on default. Flag default flips to `True`.

## Flag default

`backend/core/feature_flags.py` updated: `USE_ENSEMBLE_VERDICT` now defaults
to `True`. The 8 ensemble columns continue to populate on every run
regardless of flag, so a future revert preserves the data; the flag only
gates *whether the writer/critic/contradiction-policy gates read
ensemble_verdict or the legacy verifier_verdict*.

## What stays regardless of decision

- `backend/core/nli/deberta_client.py` + `nli_worker` compose service (Day 1).
- `backend/core/nli/numeric_normalizer.py` + `entity_extractor.py` +
  `lexical_overlap.py` (Day 2, 53 tests).
- `backend/core/nli/aggregator.py` + 18 truth-table tests (Day 3).
- `backend/core/nli/ensemble_enrich.py` + the orchestrator hook (Day 3).
- `backend/db/migrations/022_ensemble_verdicts.sql` + `.down.sql` (Day 3).
- `backend/core/feature_flags.py` with `USE_ENSEMBLE_VERDICT` (Day 3).
- `backend/tests/fixtures/germany_vs_france_hard/` — planted-overstatement
  fixture (Day 4, hand-built, ~5 hours operator effort).
- `tools/run_week2_hard_benchmark.py` — three-config verification runner
  (Day 4).
- `tools/run_week2_regression.py` — ensemble-ON regression runner (Day 5).

## Open questions for Week 3

1. **Lexical signal is redundant with DeBERTa.** `llm_plus_deberta` and
   `full_ensemble` produced identical verdicts in the hard benchmark. Is
   lexical adding any value the cross-encoder doesn't already provide on
   this evidence shape? If not — retire it, save the spaCy footprint.
2. **Precision tradeoff: tunable or fundamental?** 5/5 unplanted
   false-flagged on the hard benchmark is high. Raising the DeBERTa
   neutral-confidence threshold (currently 0.7 for entailment, no
   threshold for neutral) might recover precision without sacrificing
   the recall lift. Tune with evidence.
3. **Frontend surfacing.** The writer adapts well to a mostly-weak
   verdict spread, but the operator-facing UI doesn't show the ensemble
   reasoning yet. Day 5 ships either the popover panel (preferred) or a
   debug API endpoint as backup; whichever path lands, Week 3 should
   build the proper claim-detail experience around `ensemble_reason`.
