# Calibration — Week 21 / Day 2

Measures verifier accuracy against the W21/D1 golden set. Caches
the raw component scores so Day 3 can tune thresholds without
re-spending LLM money.

## Current calibrated truth — W24/D1 real-claim gate (PRODUCTION)

**This is the number the pilot trust claim rests on.** Measured on
**61 human-labelled real engagement claims** (Yassin, 2026-05-28)
scored through the **cross-family ensemble** (Claude + GPT-4o +
DeBERTa-v3 + lexical). It supersedes every synthetic and
synthetic-on-real-LLM measurement below.

| Metric | Value | Gate |
|--------|-------|------|
| Real FP-rate-on-supported | **0.0%** (0/7) | ≤5% → **GREEN** |
| Recall-on-insufficient | **100%** (4/4) | ≥85% safety floor ✓ |
| Recall-on-supported | 27% (7/26) | conservative (safe side) |
| Accuracy | 65.6% | — |

**Pilot verdict: GREEN — pilot proceeds with the "verified"
posture.** When the verifier says *supported*, it was right every
time on real claims. The trade-off is conservativeness: it
down-grades many genuinely-supported claims to *partial* (recall-
on-supported 27%), which means more human review of partial-flagged
claims — but it never wrongly blesses an unsupported one. Erring
toward caution is the safe direction for a trust wedge.

Run: `python backend/eval/calibration/run_calibration.py --set real
--verifier cross_family_llm`. Outputs:
`backend/eval_runs/week24_real_calibration/{summary,pilot_verdict}.json`.
Frozen as a CI floor in `tests/test_verification_quality_regression.py`
(`REAL_CLAIM_*`).

## Running

```bash
# Heuristic (no API keys) — produces an honest baseline that
# exercises the real lexical-overlap + real aggregator paths.
PYTHONPATH=backend python -m eval.calibration.report \
    --verifier heuristic_no_keys

# Real cross-family ensemble — requires API keys + DeBERTa worker.
# Budget ~$2-3 on the 60-pair set. Use this once, then rely on the
# cached raw_scores.json for any subsequent tuning.
PYTHONPATH=backend python -m eval.calibration.report \
    --verifier real_ensemble

# Replay from cache — no verifier call. Day 3 uses this with
# different aggregator thresholds.
PYTHONPATH=backend python -m eval.calibration.report --use-cache
```

## Outputs

  - `backend/eval/calibration/raw_scores.json` — the cache. Day 3
    re-aggregates from here without re-LLM.
  - `backend/eval_runs/week21_calibration/baseline.json` — the
    full report (metrics + failure cases) frozen for diffing.

## The `verifier_source` field

Always check this in `baseline.json`. It is one of:

  - `real_ensemble` — production path; numbers are calibrated truth
  - `heuristic_no_keys` — local fallback; numbers are demonstrative
    of the pipeline, not calibrated truth. Use when no API keys
    are available.
  - `cached` — replayed from `raw_scores.json` with whatever
    aggregator thresholds were in effect.
