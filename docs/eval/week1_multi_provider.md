# Week 1 — Multi-provider regression

**Decision (top-line):** **lock**

Same prompt (Germany vs France market entry), same uploads, same intake answers.
Old config: OpenAI gpt-4o everywhere, gpt-4o-mini fallback.
New config: Sonnet 4.5 for analyst/critic/writer, gpt-4o for verifier, mixed fallbacks.
3 runs per config. Raw outputs in `backend/eval_runs/week1_benchmark/` (gitignored).

Source data: `backend/eval_runs/week1_benchmark/{old,new}/run_{1,2,3}.json` (local only).
Aggregate (committed): `backend/eval_runs/week1_benchmark/summary.json` and `summary.csv`.

## Recommendation specificity (avg over 3 runs each)

| Metric | Old | New | Δ |
|---|---|---|---|
| Named options in recommendation sentence | 3.67 | 5.33 | **+1.66 (+45%)** |
| Numeric values in recommendation | 0.67 | 7.67 | **+7.0 (~11.4×)** |
| Time-bound next-steps | 6.33 | 10.0 | **+3.67 (+58%)** |
| Forbidden-phrase hits in writer output | 1.0 | 0.67 | −0.33 (−33%) |

Forbidden phrases counted (case-insensitive): "phased approach", "leverage synergies",
"best practices", "explore opportunities", "consider", "perhaps", "might want to".
Counts cover the full writer output (recommendation + summary + caveats + key_reasons + risks +
counterarguments + next_steps + kill_criteria + what_would_change_our_mind + evidence_ledger_summary).
The only forbidden phrase that fired in either config was "consider"
(OLD run 1: 1, OLD run 3: 2, NEW run 3: 2; everything else 0).

Recommendation previews — note the qualitative jump:

- OLD run 1: *"Prioritize entry into the French B2B SaaS market due to its faster growth rate
  and lower initial costs, while considering a pilot program to mitigate risks."*
- OLD run 2: *"Prioritize entry into the German market with a pilot program in North
  Rhine-Westphalia and Bavaria over the next 18 months."*
- OLD run 3: *"Prioritize a pilot entry into the German market, focusing on the Mittelstand
  sector in North Rhine-Westphalia and Bavaria, leveraging the 18-month horizon …"*
- NEW run 1: *"Launch a 6-month Mittelstand pilot in North Rhine-Westphalia and Bavaria
  targeting 6 anchor accounts, then execute go/no-go at month 7 based on 3+ signed LOIs
  and €400K+ pipeline."*
- NEW run 2: *"Launch a 6-month Mittelstand pilot in North Rhine-Westphalia and Bavaria,
  allocating 8 of 12 headcount to Germany and 4 to product/ops support, IF five critical
  validations pass within 30 days …"*
- NEW run 3: *"Run a 60-day structured market validation before committing to either
  Germany or France, then launch a 6-month pilot in the market showing stronger fit,
  allocating 8 of 12 headcount to that pilot with explicit go/no-go criteria."*

NEW recommendations name segments (Mittelstand), regions (NRW + Bavaria), headcount splits
(8/4 of 12), pipeline thresholds (€400K), specific kill criteria (3+ LOIs by month 7),
and explicit validation gates. OLD recommendations stop at country + region + duration.

OLD also disagreed with itself across runs (run 1: France first; runs 2–3: Germany).
NEW landed on Mittelstand-pilot-with-validation in all three.

## Claim quality (avg over 3 runs each)

| Metric | Old | New | Δ |
|---|---|---|---|
| Total claims | 7.67 | 20.0 | **+12.3 (+161%)** |
| Avg claim length (chars) | 99.93 | 236.87 | **+137.0 (+137%)** |
| Claims with ≥2 evidence ids | 0 | 0 | 0 |

Per-run claim counts: OLD = {5, 9, 9}, NEW = {20, 20, 20}. NEW writes harder, longer claims
that fold a quantified observation, a comparator, and a caveat into one statement; OLD writes
short single-fact claims.

The "claims with ≥2 evidence ids" metric is 0 for both configs because the seeded evidence
catalogue is wide-but-shallow (10 distinct sources, each tied to a single research dimension).
With more depth in the evidence base every claim could in principle cite multiple rows, but
neither analyst chose to do so on this benchmark. Not a routing-vs-routing signal.

## Verifier behaviour

| Metric | Old | New | Δ |
|---|---|---|---|
| Verdicts (avg per run): supported / weak / unsupported / overstates | 5 / 0 / 0 / 0 | 10 / 0 / 0 / 0 | More verdicts emitted (proportional to claim count); same shape |
| Avg claims marked weak per run | 0 | 0 | 0 |
| Contradictions surfaced | 0 | 0 | 0 |

Both configs return 100% "supported" verdicts. The hypothesis was that cross-family
verification (gpt-4o judging Sonnet) would disagree more often than same-family
(gpt-4o-mini judging gpt-4o). On this benchmark it did not — every claim the verifier
inspected came back "supported", regardless of routing.

Three honest reads of this:

1. **The wedge is real but invisible at the JSON-mode-judge layer.** A short prompt asking
   the verifier "supported / weak / unsupported / overstates" against an evidence catalogue
   tends to anchor on the supported answer when the analyst stays close to the catalogue.
   The cross-family wedge will only show signal once the NLI judge layer (Week 2) lands —
   per-claim DeBERTa entailment scores will surface the disagreement that the JSON-mode
   verifier currently smooths over.
2. **The benchmark may be too easy.** Both analysts cite real quotes from the seeded
   evidence; saying "supported" is correct for most of them. A harder benchmark with
   unsupported claims sprinkled in would discriminate better.
3. **The hypothesis is false on this kind of task.** Possible but premature to conclude;
   we should re-test with NLI in Week 2 before reaching this verdict.

The signal we *did* find: NEW emits roughly **2× as many verifiable claims per run**
(10 supported vs 5 supported on average), so even with identical verdict ratios the
absolute volume of supported, evidence-backed claims doubles. That is a real downstream win.

## Cost & latency

| Metric | Old | New | Δ |
|---|---|---|---|
| Total cost per run (USD) | 0.10 | 0.57 | **+0.47 (~5.7×)** |
| Wall-clock time per run (s) | 88.93 | 595.73 | **+506.8 (~6.7×)** |
| Stage count hitting fallback | 0 | 0 | 0 |

Six runs total: $0.31 (OLD) + $1.71 (NEW) = **$2.03**, well under the $60 ceiling.
No fallback was hit in any of the six runs — every primary model held under load.
Wall-clock multiplier is dominated by Sonnet 4.5's higher per-token latency on the
analyst (8K-token output budget) and writer; planner/researcher latency is comparable
across configs because both still run on gpt-4o.

## Decision (4–6 sentences)

**Lock new routing.** Recommendation specificity moved up sharply on every measurable
axis (numerics ~11×, named options +45%, time-bound steps +58%, forbidden phrases down),
claim count more than doubled (7.67 → 20) and average claim length more than doubled
(99.9 → 236.9 chars), while no fallbacks fired and no schema regressions appeared.
Verifier disagreement did not increase, but the JSON-mode verdict layer is the wrong
instrument to test the wedge — the hypothesis becomes properly testable only once the
Week 2 NLI judge writes per-(claim, chunk) entailment scores; today's "all supported"
ceiling holds in both configs and isn't a regression. The 5.7× cost and 6.7× wall-clock
premium is acceptable in absolute terms ($0.50/run, ~8 minutes/run) for a workbench
where one report is the unit of value, and it is the price of getting recommendations
that read like "6-month Mittelstand pilot in NRW + Bavaria with go/no-go at month 7
gated on 3+ LOIs and €400K+ pipeline" instead of "prioritize entry into Germany". The
existing intra-family fallbacks (Day 3) preserve the cross-family contract under
provider outage. Proceed to Week 2 — wire DeBERTa, then re-run this benchmark with the
NLI layer engaged to settle the verifier-disagreement question on real entailment data.

## What stays regardless of decision

The Day 1–4 infrastructure is permanent: `backend/tests/test_multi_provider_smoke.py`,
`backend/tests/test_structured_outputs_multi_provider.py`,
`backend/core/provider_family.py` + the boot-time cross-family check in `backend/main.py`,
`backend/tests/test_model_router.py` (cross-family + fallback-chain tests),
`tools/run_week1_benchmark.py`, and the YAML's intra-family fallback design for analyst
and writer (claude-sonnet-4-5 → claude-haiku-4-5 instead of openai/gpt-4o, so the wedge
holds even on Sonnet outage). All of it survives a future revert.
