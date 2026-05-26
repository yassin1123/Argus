# Calibration — Week 21 / Day 2

Measures verifier accuracy against the W21/D1 golden set. Caches
the raw component scores so Day 3 can tune thresholds without
re-spending LLM money.

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
