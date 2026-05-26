"""Calibration baseline report — Phase 5 / Week 21 / Day 2.

Assembles the JSON report from a fresh calibration run + writes
it to ``backend/eval_runs/week21_calibration/baseline.json``.
Stable across re-runs of the same cached raw_scores so Day 3's
tuned report can diff against this baseline.

Hard rule: this script reports the ugly truth. The W20 production
distribution showed 88.89% "supported" — that number is real
volume, not real accuracy. After today, we know what fraction of
that supported volume was a false positive. That's the trust
metric the pilots need.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metrics import compute_metrics, split_failures
from .runner import (
    HeuristicVerifier,
    RealEnsembleVerifier,
    VerifierProtocol,
    run_calibration,
)


_BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_OUT = (
    _BACKEND / "eval_runs" / "week21_calibration" / "baseline.json"
)
DEFAULT_RAW = (
    _BACKEND / "eval" / "calibration" / "raw_scores.json"
)


def select_verifier(name: str | None) -> VerifierProtocol:
    """Pick the verifier by name. Defaults to heuristic so a run
    without API keys still produces an honest baseline."""
    if name == "real_ensemble":
        return RealEnsembleVerifier()
    return HeuristicVerifier()


def write_baseline_report(
    *,
    verifier_name: str | None = None,
    use_cache: bool = False,
    max_pairs: int | None = None,
    out_path: Path | None = None,
    raw_path: Path | None = None,
) -> dict[str, Any]:
    """End-to-end: run (or replay) the calibration -> compute
    metrics -> write the baseline JSON. Returns the in-memory
    report dict (handy for tests + the manual smoke)."""
    raw_path = raw_path or DEFAULT_RAW
    out_path = out_path or DEFAULT_OUT
    verifier = None
    if not use_cache:
        verifier = select_verifier(verifier_name)

    pairs = run_calibration(
        verifier=verifier,
        raw_scores_path=raw_path,
        use_cache=use_cache,
        max_pairs=max_pairs,
    )
    metrics = compute_metrics(pairs)
    failures = split_failures(pairs)

    report = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "verifier_source": (
            verifier.name if verifier is not None else "cached"
        ),
        "raw_scores_path": str(raw_path),
        "headline": {
            "accuracy": metrics.accuracy,
            "fp_rate_on_supported": metrics.fp_rate_on_supported,
            "recall_on_insufficient": metrics.recall_on_insufficient,
            "adversarial_accuracy": metrics.adversarial_accuracy,
        },
        "metrics": metrics.to_dict(),
        "failure_cases": failures,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--verifier", choices=["heuristic_no_keys", "real_ensemble"],
        default="heuristic_no_keys",
        help="Verifier implementation to run. Defaults to "
             "heuristic_no_keys so a no-LLM run produces a baseline.",
    )
    ap.add_argument(
        "--use-cache", action="store_true",
        help="Replay from raw_scores.json instead of running the verifier.",
    )
    ap.add_argument("--max-pairs", type=int, default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    args = ap.parse_args(argv)

    report = write_baseline_report(
        verifier_name=args.verifier,
        use_cache=args.use_cache,
        max_pairs=args.max_pairs,
        out_path=Path(args.out),
        raw_path=Path(args.raw),
    )

    h = report["headline"]
    m = report["metrics"]
    print()
    print(f"=== W21/D2 baseline ({report['verifier_source']}) ===")
    print(f"  pairs: {m['pair_count']}   correct: {m['correct']}   "
          f"accuracy: {h['accuracy']:.2%}")
    print(f"  FP rate on supported: {h['fp_rate_on_supported']:.2%} "
          f"({m['fp_count_on_supported']} / {m['supported_predictions']})")
    print(f"  Recall on insufficient: {h['recall_on_insufficient']:.2%} "
          f"({m['insufficient_caught']} / {m['insufficient_total']})")
    print(f"  Adversarial accuracy:   {h['adversarial_accuracy']:.2%} "
          f"(n={m['adversarial_count']})")
    print()
    print("  per-class:")
    for c in m["per_class"]:
        print(f"    {c['label']:14s} P={c['precision']:.2f} "
              f"R={c['recall']:.2f} F1={c['f1']:.2f} "
              f"(support {c['support']})")
    print()
    print("  per-category accuracy:")
    for cat, acc in m["per_category_accuracy"].items():
        n = m["per_category_pair_count"][cat]
        print(f"    {cat:18s} {acc:.2%} (n={n})")
    print()
    print(f"  failure cases — FP {len(report['failure_cases']['false_positives'])}"
          f" / FN {len(report['failure_cases']['false_negatives'])}"
          f" / other {len(report['failure_cases']['other_disagreements'])}")
    print()
    print(f"  baseline written -> {args.out}")
    print(f"  raw scores cached -> {args.raw}")
    return 0


__all__ = ["DEFAULT_OUT", "DEFAULT_RAW", "select_verifier", "write_baseline_report"]


if __name__ == "__main__":
    raise SystemExit(main())
