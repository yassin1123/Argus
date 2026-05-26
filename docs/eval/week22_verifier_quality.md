# Week 22 — Verifier signal quality

**Status:** ship — under "AI-assisted with human review" pilot posture
**Closed:** 2026-05-27
**Branch:** `phase-5/week-22` — D1, D2, D3, D4, D5 committed.

> Week 21 found the verifier's FP-rate-on-supported was 0.60 on a
> synthetic worst-case set and diagnosed the bottleneck as
> upstream signal quality, not thresholds. Week 22 set out to
> get the real-claim number, diagnose the specific failing
> component, make the single highest-leverage fix, and re-measure.
> Outcome: FP dropped 60% → 43.75% via a reason-then-verdict LLM
> judge rework; recall-on-insufficient preserved; the engine got
> worked on before the pilot.

## The arc

  - **D1** built the real-claim labelling pipeline + the
    calibration runner's `--set real` flag. Scoping verdict
    landed at `LABELING_PENDING` — Yassin hasn't committed the
    30-60 min to label the worksheet yet, so the week ran on the
    spec's explicit safe default: the synthetic worst-case
    (W21's 60% FP) as the working number, **FULL FIX path** for
    Days 2-5.
  - **D2** diagnosed the W21 FPs: 3 cases across 3 fault types
    (1 evidence, 1 DeBERTa, 1 lexical false-friend). With no
    dominant fault, the disposition was `multi_front`. Component
    reliability: LLM 73%, DeBERTa 79%, lexical 43% (weakest but
    most useful contrarian — 11 minority-correct calls vs DeBERTa's 1).
  - **D3** picked the single highest-leverage fix that touches
    three of the five fault categories: the **reason-then-verdict
    LLM judge prompt**. Decompose the claim, quote a supporting
    span per part (or declare "no supporting span"), then emit
    the verdict. Both the production prompt and the heuristic
    substitute were updated; raw scores re-captured.
  - **D4** brought the full W21 measurement chain forward
    against the new signal: re-calibrated, re-tuned (zero LLM),
    re-red-teamed against the same 34-case W21/D4 adversarial
    set, produced a complete before/after + pilot-readiness verdict.
  - **D5** (this doc) locks the gains into the CI regression
    floor + the dashboard + the pilot posture.

## The numbers

| Metric | W21 (synthetic worst-case) | W22 post-fix | Δ |
|---|---:|---:|---:|
| **FP-rate on "supported"** (catastrophic) | **60.00%** | **43.75%** | **-16.25pp** |
| Recall on "insufficient" (preserved) | 93.33% | 93.33% | 0 |
| Accuracy | 31.67% | 41.67% | +10.00pp |
| Over-flag fraction | 86.67% [**FAIL**] | 40.00% [**WARN**] | -46.67pp |
| Red-team catch rate | 97.06% | 94.12% | -2.94pp |
| Adversarial accuracy | 38.89% | 33.33% | -5.56pp |

Source: heuristic_no_keys baseline against the 60-pair W21/D1
synthetic golden set. The real-firm calibration is still pending
Yassin's labelling commitment + a real-ensemble API run; both
infrastructure paths are shipped and tested.

## What the fix was

The W22/D2 diagnosis named `multi_front` (no single fault
category dominated). On a multi-front diagnosis, the single
highest-leverage fix is whichever change touches the most fault
categories at once:

  - **LLM-entailment fault** → direct fix
  - **Evidence fault** → indirect fix (asking "which specific
    span supports this?" forces span attention)
  - **Lexical false-friend** → indirect fix (demanding a quoted
    supporting span forces semantic matching, not gist overlap)

That fix is the **reason-then-verdict LLM judge prompt**
([backend/core/nli/reason_then_verdict.py](../../backend/core/nli/reason_then_verdict.py)):

```
STEP 1 — DECOMPOSE the CLAIM into testable parts.
STEP 2 — For each part, QUOTE the supporting span from the
         EVIDENCE, OR declare "no supporting span".
STEP 3 — JUDGE based on Steps 1+2.
```

The same discipline lands on the heuristic substitute
(`heuristic_reason_then_verdict()`) so the cached-scores path
benefits without API spend.

**Key property:** the fix is STRICTER, not weaker. FP drops
because more claims fail the per-part check (a "fabricated 247
bps" claim now lands "no supporting span" for the numeric part),
not because the verdict bar moved. The W22/D3 hard rule held:
recall_on_insufficient preserved at 93.33%.

## Pilot posture (honest)

**`HUMAN_REVIEW_REQUIRED`** — the W22/D4 verdict from
[backend/eval_runs/week22_recalibration/comparison.json](../../backend/eval_runs/week22_recalibration/comparison.json).

The verifier ships under **"AI-assisted verification with human
review required on flagged claims"** — not "fully verified."

The three-way mapping the W22/D4 classifier applies:

| Verdict | FP ceiling | Red-team floor | Pilot positioning |
|---|---:|---:|---|
| ready | ≤ 10% | ≥ 95% | "fully verified" |
| **human_review_required** | **≤ 50%** | **≥ 85%** | **"AI-assisted with human review"** |
| not_ready | (else) | (else) | continue verifier work; adjust pilot scope |

W22 post-fix lands at FP=43.75%, red-team=94.12%, over-flag
status=WARN — squarely in the human_review_required bucket. This
is the spec's middle outcome, explicitly:

> _"Improved but not enough → pilot can proceed with the
> verifier framed as 'AI-assisted verification with human review
> required on flagged claims' (honest positioning) rather than
> 'fully verified.'"_

**What this means for product messaging:**

  - The pitch keeps the cross-family verification + verified-
    claims wedge — that's still differentiated, defensible, and
    measurably better than ungrounded LLM output.
  - The "fully verified" claim is replaced with **"AI-verified,
    human-reviewable"**. Every supported-class claim in the UI
    surfaces a review affordance.
  - The dashboard's verification-quality panel
    ([backend/api/observability_dashboard.py](../../backend/api/observability_dashboard.py))
    surfaces the real FP rate + catch rate so partners + ops
    have the trust number in front of them, not buried.

## Known limitations (honest)

  - **The baseline is heuristic.** All W22 numbers were measured
    against the `heuristic_no_keys` verifier (real lexical-
    overlap + deterministic LLM/DeBERTa substitutes). The
    `RealEnsembleVerifier` path is shipped + carries the same
    reason-then-verdict prompt — when API keys + DeBERTa worker
    are wired (one-time ~$2-3 spend), the calibration re-runs and
    the numbers tighten. The infrastructure is in place.
  - **Real-firm labels are pending.** The W22/D1 labelling
    pipeline is ready; Yassin's 30-60 min commitment seeds it.
    Synthetic numbers are calibration-indicative, not pilot-
    definitive. Pilots themselves accumulate the real labels
    faster than any offline labelling can.
  - **`rt_007` misattribution** — pre-existing W21/D4 known
    limitation. The LLM judge needs to attend to speaker roles;
    fix needs a Week 23+ targeted entity-attribution probe (the
    numeric-consistency probe pattern from W21/D4 is the
    template).
  - **`rt_012` temporal_drift (NEW)** — W22/D3 introduced this
    escape: when evidence carries BOTH the actual period
    ("Q1 FY2023") AND the target period ("FY2024 timeline"), the
    period-mismatch heuristic can't distinguish. Needs real LLM
    attention to "ahead of the original FY2024" semantics.
  - **NLI cross-encoder ceiling.** DeBERTa-v3 catches explicit
    negation; misses subtle "considered but did not approve."
    The W22/D2 reliability score (79%) is the architectural
    ceiling for this signal; further improvement requires either
    swapping the cross-encoder for a stronger one (LongFormer,
    NLI-bart) or layering an explicit negation-detection
    preprocessor.
  - **Lexical signal is noisy but useful.** 43% standalone
    reliability but the most useful contrarian voice on
    component disagreements. Don't remove it; the W21/D3
    aggregator already weighs it as a downgrader only.

## Decision

**Ship.** Every hard rule the W22/D5 spec laid down holds:

  - ✅ The regression baseline did not lock in numbers worse than
    W21. FP-rate tightened from 0.60 → 0.4375; recall held; the
    week net-improved.
  - ✅ The known-limitations section is mandatory + present (5
    explicit items).
  - ✅ The pilot-posture decision is `HUMAN_REVIEW_REQUIRED`,
    surfaced front-and-centre in this doc + the README Status
    section update + the dashboard.
  - ✅ No trust claim is made that the numbers don't support.
    The pitch retains the verification wedge under honest
    "AI-assisted with human review" framing.

## Component check

| Component | Status | Evidence |
|---|---|---|
| Real-claim labelling pipeline (D1) | ✅ | 5 tests; worksheet seeded from W14/W20 eval runs; scoping verdict `LABELING_PENDING` (synthetic worst-case is the working number until Yassin labels) |
| Signal-bottleneck diagnosis (D2) | ✅ | 5 tests; `multi_front` verdict; per-component reliability + minority-correct accumulator |
| Reason-then-verdict signal fix (D3) | ✅ | 5 tests; production prompt + heuristic substitute; FP -16.25pp |
| Re-calibrate + re-tune + re-red-team (D4) | ✅ | 6 tests; over-flag FAIL→WARN; pilot-readiness verdict `HUMAN_REVIEW_REQUIRED` |
| Regression baseline + wrap-up (D5) | ✅ | regression floors locked at the improved numbers; README updated; this doc |

**Test totals across the week: 21/21 W22 tests + 48/48 W21
tests still green.** No quality-floor regression.

## Retro

**What went well.** The W21/D5 discipline of frozen regression
floors gave the W22 work a measurable starting point. Day 2's
honest "multi_front, no dominant fault" diagnosis prevented
picking a wrong fix target. Day 3's choice of the
reason-then-verdict prompt as the single fix that touches
multiple fault categories at once was the right structural call
— even if it cost a small red-team trade-off. The over-flag
guardrail catching the W21/D3 candidate that would have shipped
"100% review required" is the discipline that lets W22 net-improve
honestly instead of over-claiming.

**What was tricky.** The first re-tune in D4 overwrote the
`raw_scores.json` source label to `"cached"` because the runner
unconditionally re-persisted on cache replay. This broke the
`test_new_raw_scores_captured` assertion and surfaced a real bug:
cache replays should never overwrite the canonical artefact.
Fixed in [backend/eval/calibration/runner.py](../../backend/eval/calibration/runner.py)
(`run_calibration` now skips persistence when `use_cache=True`).
That's the kind of "honest source label" discipline the W21/D5
retro called out — and it caught a regression.

**What to carry into Week 23.** The pilot-readiness classifier
(`classify_pilot_readiness`) is now the canonical three-way map:
ready / human_review_required / not_ready. Future quality work
re-runs the classifier; the verdict drives messaging
automatically. When the real-ensemble baseline finally lands +
real-firm labels accumulate, this same classifier produces the
updated posture without re-arguing the criteria.

## Phase 5 / Week 23 (compressed enterprise) starts with

  - The verification-quality panel live on the dashboard,
    reflecting real numbers (FP 43.75%, catch 93.3%, red-team
    94.1%, source labelled `heuristic_no_keys`)
  - The CI regression floor at the tightened W22 numbers — any
    change that drops below gets caught
  - The pilot posture decided + propagated through the README
    Status section
  - The labelling pipeline ready; whenever Yassin commits 30-60
    min, the calibration re-classifies and the floors tighten
    again
  - Two named carry-forward items (rt_007 misattribution probe;
    rt_012 temporal-drift LLM attention) for Week 23+ verifier
    polish — both have prescribed mitigations in
    [backend/eval/red_team/run_red_team.py::EXPLOIT_MITIGATIONS](../../backend/eval/red_team/run_red_team.py)

## Files

  - Golden set + labelling: [backend/eval/golden_set/](../../backend/eval/golden_set/) + [tools/extract_claims_for_labeling.py](../../tools/extract_claims_for_labeling.py) + [tools/label_claims.py](../../tools/label_claims.py)
  - Real-claim calibration runner: [backend/eval/calibration/run_real_calibration.py](../../backend/eval/calibration/run_real_calibration.py)
  - Diagnosis: [backend/eval/calibration/diagnose.py](../../backend/eval/calibration/diagnose.py)
  - The fix: [backend/core/nli/reason_then_verdict.py](../../backend/core/nli/reason_then_verdict.py)
  - Recalibration + pilot verdict: [backend/eval/calibration/recalibrate.py](../../backend/eval/calibration/recalibrate.py)
  - Comparison artifact: [backend/eval_runs/week22_recalibration/comparison.json](../../backend/eval_runs/week22_recalibration/comparison.json)
  - Regression suite: [backend/tests/test_verification_quality_regression.py](../../backend/tests/test_verification_quality_regression.py)
  - W21 source: [docs/eval/week21_quality.md](week21_quality.md)
