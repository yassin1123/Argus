"""Verifier calibration measurement — Phase 5 / Week 21 / Day 2.

Three modules:

  - :mod:`runner` — drives the real verification path (LLM judge +
    DeBERTa + lexical → aggregator) against the golden set and
    caches per-pair raw component scores so Day 3 threshold-tuning
    runs against the cache, not the LLM
  - :mod:`metrics` — pure functions over (predicted, ground-truth)
    pairs: confusion matrix, per-class precision/recall/F1,
    FP-rate-on-supported (the catastrophic-error metric), recall
    on insufficient (the catch rate), per-category breakdown
  - :mod:`report` — assembles a JSON baseline that's stable across
    re-runs of the SAME cached scores, so Day 3's tuning report
    can diff against today's
"""

from .metrics import (
    CalibrationMetrics,
    compute_metrics,
    confusion_matrix,
)
from .runner import (
    RawScores,
    ScoredPair,
    VerifierProtocol,
    run_calibration,
)

__all__ = [
    "CalibrationMetrics",
    "RawScores",
    "ScoredPair",
    "VerifierProtocol",
    "compute_metrics",
    "confusion_matrix",
    "run_calibration",
]
