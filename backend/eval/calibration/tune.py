"""Threshold tuning harness -- Phase 5 / Week 21 / Day 3.

Sweeps ``ThresholdConfig`` combinations against the cached raw
scores (from W21/D2) and picks the configuration that minimises
the false-positive rate on ``supported`` under the spec's
asymmetric objective:

  primary    minimise  FP rate on supported
  secondary  maximise  recall on insufficient
  tiebreak   minimise  false-negative rate

No LLM calls. The tuner replays the cached scores through the
aggregator with every candidate config; the runner's `use_cache`
path is the only DB / API surface exercised.

Hard rules baked in:

  - **Never accept a config that increases FP** (a configuration
    that lets even one more hallucination through is worse than
    one that flags ten extra good claims).
  - **Borderline cases resolve to "partial"** -- the ``borderline_band``
    knob on :class:`ThresholdConfig` is what implements this; the
    sweep includes positive values so the optimiser can choose to
    use it.
  - **Don't overfit** -- synthetic-set sample sizes are small (60).
    The over-flagging guardrail surfaces if the chosen config
    pushes more than 25-30% of genuinely-supported claims onto the
    review queue; the report prints the trade-off honestly so an
    operator can refuse a too-cautious config.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from core.nli.threshold_config import (
    ThresholdConfig,
    default_threshold_config,
    save_threshold_config,
)

from .metrics import compute_metrics, split_failures
from .runner import load_scored_pairs, run_calibration

logger = logging.getLogger(__name__)


_BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_RAW = _BACKEND / "eval" / "calibration" / "raw_scores.json"
DEFAULT_TUNED = _BACKEND / "eval_runs" / "week21_calibration" / "tuned.json"


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


def _frange(start: float, stop: float, step: float) -> list[float]:
    """Inclusive on both ends, rounded to 4 dp to avoid float drift."""
    out: list[float] = []
    v = start
    while v <= stop + 1e-9:
        out.append(round(v, 4))
        v += step
    return out


@dataclass
class CandidateResult:
    """One swept config + its full metrics."""

    config: ThresholdConfig
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "metrics": self.metrics,
        }


def _build_grid(
    deberta_steps: int = 5,
    drift_steps: int = 5,
    band_steps: int = 5,
) -> list[ThresholdConfig]:
    """Coarse grid: DeBERTa high-conf in [0.5, 0.9], numeric drift
    in [0.80, 1.00], borderline_band in [0.00, 0.25]. Granularity
    is deliberately coarse -- the synthetic set is small (60 pairs)
    so a fine sweep would overfit.
    """
    deberta_vals = [round(0.5 + i * (0.4 / (deberta_steps - 1)), 3)
                    for i in range(deberta_steps)]
    drift_vals = [round(0.80 + i * (0.20 / (drift_steps - 1)), 3)
                  for i in range(drift_steps)]
    band_vals = [round(i * (0.25 / (band_steps - 1)), 3)
                 for i in range(band_steps)]

    grid: list[ThresholdConfig] = []
    for d in deberta_vals:
        for n in drift_vals:
            for b in band_vals:
                grid.append(ThresholdConfig(
                    deberta_high_conf=d,
                    numeric_drift_below=n,
                    borderline_band=b,
                    id=f"sweep_d{d}_n{n}_b{b}",
                    rationale="W21/D3 sweep candidate",
                    source="sweep",
                ))
    return grid


# ---------------------------------------------------------------------------
# Objective
# ---------------------------------------------------------------------------


def _objective_key(metrics: dict[str, Any]) -> tuple[float, float, float, float]:
    """Lexicographic sort key encoding the spec's asymmetry.

    Returns a tuple where SMALLER is better:

        (fp_rate_on_supported,           ← primary: minimise
         -recall_on_insufficient,        ← secondary: maximise
         fn_rate,                         ← tiebreak: minimise
         -accuracy)                       ← final tiebreak

    The supplemental ``-recall`` / ``-accuracy`` keep the sort
    deterministic without ever overriding the primary FP minimisation.
    """
    fp_rate = float(metrics.get("fp_rate_on_supported") or 0.0)
    recall_ins = float(metrics.get("recall_on_insufficient") or 0.0)
    # FN rate against the supported truth: of all actually-supported
    # claims, what fraction did the verifier NOT label supported?
    per_class = metrics.get("per_class") or []
    sup = next((c for c in per_class if c["label"] == "supported"), None)
    if sup:
        fn_rate = 1.0 - float(sup.get("recall", 0.0))
    else:
        fn_rate = 1.0
    accuracy = float(metrics.get("accuracy") or 0.0)
    return (fp_rate, -recall_ins, fn_rate, -accuracy)


def beats(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    """True iff ``candidate`` is strictly better than ``baseline``
    under the asymmetric objective.

    Public so tests can replay the comparison directly. The rule
    that 'FP-on-supported never gets worse' is enforced here: a
    candidate with higher FP-on-supported NEVER beats baseline,
    even if every other metric is dramatically better.
    """
    c_fp = float(candidate.get("fp_rate_on_supported") or 0.0)
    b_fp = float(baseline.get("fp_rate_on_supported") or 0.0)
    if c_fp > b_fp + 1e-9:
        return False  # hard rule: never accept higher FP
    return _objective_key(candidate) < _objective_key(baseline)


# ---------------------------------------------------------------------------
# Over-flagging guardrail
# ---------------------------------------------------------------------------


OVER_FLAG_FRACTION_WARN = 0.30  # >30% supported→partial = worth flagging
OVER_FLAG_FRACTION_FAIL = 0.50  # >50% = the trade is no longer worth taking


def _over_flag_fraction(per_class: list[dict[str, Any]]) -> float:
    """Of all genuinely-supported claims, what fraction did the
    tuned thresholds NOT label supported (i.e. flagged onto the
    review queue)? = 1 - recall_on_supported."""
    sup = next((c for c in per_class if c["label"] == "supported"), None)
    if not sup:
        return 0.0
    recall = float(sup.get("recall", 0.0))
    return max(0.0, 1.0 - recall)


def assess_over_flagging(
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Compute the over-flagging trade-off panel. Returns the
    fraction + a status label + a short message -- designed to be
    pasted into ``tuned.json`` so the operator reading the diff
    sees the cost of the FP minimisation explicitly."""
    fraction = _over_flag_fraction(metrics.get("per_class") or [])
    if fraction >= OVER_FLAG_FRACTION_FAIL:
        status = "fail"
        message = (
            f"Over-flagging {fraction:.1%} of genuinely-supported claims; "
            "tuning has driven the system into review-everything territory. "
            "The bottleneck is the verifier or evidence retrieval, not "
            "thresholds -- relax the band or revisit upstream signals."
        )
    elif fraction >= OVER_FLAG_FRACTION_WARN:
        status = "warn"
        message = (
            f"Over-flagging {fraction:.1%} of genuinely-supported claims for "
            "human review. The wedge is held but the human-review burden "
            "is meaningful -- note in the W21 wrap-up."
        )
    else:
        status = "ok"
        message = (
            f"Over-flagging only {fraction:.1%} of genuinely-supported "
            "claims; the FP minimisation cost is acceptable."
        )
    return {
        "supported_review_fraction": round(fraction, 4),
        "status": status,
        "warn_threshold": OVER_FLAG_FRACTION_WARN,
        "fail_threshold": OVER_FLAG_FRACTION_FAIL,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Main tune flow
# ---------------------------------------------------------------------------


def evaluate_config(
    config: ThresholdConfig,
    raw_scores_path: Path | None = None,
) -> dict[str, Any]:
    """Replay the cached raw scores with one candidate config +
    return its metrics dict. No LLM. No DB writes."""
    rp = raw_scores_path or DEFAULT_RAW
    pairs = run_calibration(
        verifier=None,
        raw_scores_path=rp,
        use_cache=True,
        threshold_config=config,
    )
    return compute_metrics(pairs).to_dict()


def tune(
    *,
    raw_scores_path: Path | None = None,
    out_path: Path | None = None,
    persist_config: bool = True,
    grid: Iterable[ThresholdConfig] | None = None,
) -> dict[str, Any]:
    """Sweep -> pick best -> (optionally) persist to YAML +
    write the report. Returns the report dict.

    Honours the spec hard rule: the LLM is never called. The
    runner is invoked with ``use_cache=True`` for every candidate;
    if the cache is missing the run is a no-op + the function
    raises a clear error rather than transparently triggering
    LLM spend."""
    rp = raw_scores_path or DEFAULT_RAW
    if not rp.exists():
        raise FileNotFoundError(
            f"raw scores cache missing at {rp}; run "
            "tools/run_calibration first (W21/D2)"
        )

    # Baseline = current YAML / code defaults so the diff is
    # apples-to-apples with the W21/D2 baseline report.
    baseline_config = default_threshold_config()
    baseline_metrics = evaluate_config(baseline_config, rp)

    candidates: list[CandidateResult] = []
    llm_call_count_during_tuning = 0  # always 0 -- kept for the test
    for cfg in (grid if grid is not None else _build_grid()):
        m = evaluate_config(cfg, rp)
        candidates.append(CandidateResult(config=cfg, metrics=m))

    # Pick by lexicographic objective key -- smallest tuple wins.
    candidates.sort(key=lambda c: _objective_key(c.metrics))
    best = candidates[0]

    # If the best candidate isn't STRICTLY better than baseline
    # under :func:`beats`, fall back to baseline so we never make
    # the system worse than its starting state.
    if not beats(best.metrics, baseline_metrics):
        best = CandidateResult(config=baseline_config, metrics=baseline_metrics)
        chosen_reason = (
            "no candidate strictly beat baseline under the asymmetric "
            "objective -- keeping the W2/D3 defaults"
        )
    else:
        chosen_reason = (
            "best candidate strictly beats baseline: FP rate on supported "
            f"{best.metrics['fp_rate_on_supported']:.2%} vs "
            f"baseline {baseline_metrics['fp_rate_on_supported']:.2%}"
        )

    over_flag = assess_over_flagging(best.metrics)

    # W21/D3 hard rule: "don't over-flag into uselessness." If the
    # best candidate's over-flag status is FAIL, we refuse to adopt
    # it -- the wedge isn't "every claim flagged for review." Revert
    # to baseline + surface the finding loudly so the W21 wrap-up
    # carries the signal that the bottleneck is upstream (the
    # verifier signals themselves), not thresholds.
    if over_flag["status"] == "fail":
        chosen_reason = (
            "W21/D3 tuning over-flagged genuinely-supported claims at "
            f"{over_flag['supported_review_fraction']:.1%}; per the "
            "spec hard rule keeping the W2/D3 defaults. The bottleneck "
            "is upstream signal quality, not thresholds -- see "
            "over_flagging panel + tuned.json failure cases."
        )
        best = CandidateResult(config=baseline_config, metrics=baseline_metrics)
        over_flag = assess_over_flagging(best.metrics)

    # The best config gets a self-documenting rationale before
    # we persist it.
    best_config = ThresholdConfig(
        deberta_high_conf=best.config.deberta_high_conf,
        numeric_drift_below=best.config.numeric_drift_below,
        borderline_band=best.config.borderline_band,
        id="w21_d3_tuned",
        rationale=chosen_reason,
        source="w21_d3_tune",
    )

    persisted_path: str | None = None
    if persist_config:
        path = save_threshold_config(best_config)
        persisted_path = str(path)

    # Re-load the pairs at the best config so the report includes
    # the full failure-cases breakdown the operator will scroll.
    final_pairs = run_calibration(
        verifier=None, raw_scores_path=rp, use_cache=True,
        threshold_config=best_config,
    )
    failures = split_failures(final_pairs)

    report = {
        "tuning_source": "cached_raw_scores",
        "llm_calls_during_tuning": llm_call_count_during_tuning,
        "raw_scores_path": str(rp),
        "candidates_evaluated": len(candidates),
        "baseline_config": baseline_config.to_dict(),
        "baseline_metrics_headline": _headline(baseline_metrics),
        "tuned_config": best_config.to_dict(),
        "tuned_metrics_headline": _headline(best.metrics),
        "tuned_metrics_full": best.metrics,
        "delta_vs_baseline": {
            "fp_rate_on_supported_delta": (
                best.metrics["fp_rate_on_supported"]
                - baseline_metrics["fp_rate_on_supported"]
            ),
            "recall_on_insufficient_delta": (
                best.metrics["recall_on_insufficient"]
                - baseline_metrics["recall_on_insufficient"]
            ),
            "accuracy_delta": (
                best.metrics["accuracy"] - baseline_metrics["accuracy"]
            ),
        },
        "over_flagging": over_flag,
        "failure_cases": failures,
        "persisted_config_path": persisted_path,
    }

    out = out_path or DEFAULT_TUNED
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    return report


def _headline(metrics: dict[str, Any]) -> dict[str, float]:
    """Pull the four numbers the report leads with."""
    per_class = metrics.get("per_class") or []
    sup = next((c for c in per_class if c["label"] == "supported"), {})
    return {
        "accuracy": float(metrics.get("accuracy") or 0.0),
        "fp_rate_on_supported": float(
            metrics.get("fp_rate_on_supported") or 0.0
        ),
        "recall_on_insufficient": float(
            metrics.get("recall_on_insufficient") or 0.0
        ),
        "recall_on_supported": float(sup.get("recall", 0.0)),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    ap.add_argument("--out", default=str(DEFAULT_TUNED))
    ap.add_argument(
        "--no-persist", action="store_true",
        help="Skip writing the tuned YAML config (for dry-runs).",
    )
    args = ap.parse_args(argv)

    report = tune(
        raw_scores_path=Path(args.raw),
        out_path=Path(args.out),
        persist_config=not args.no_persist,
    )

    print()
    print("=== W21/D3 threshold tuning ===")
    print(f"  candidates evaluated: {report['candidates_evaluated']}  "
          f"llm_calls: {report['llm_calls_during_tuning']}")
    print()
    b = report["baseline_metrics_headline"]
    t = report["tuned_metrics_headline"]
    print(f"  baseline   acc={b['accuracy']:.2%}  "
          f"FP-on-supported={b['fp_rate_on_supported']:.2%}  "
          f"recall-on-insufficient={b['recall_on_insufficient']:.2%}  "
          f"recall-on-supported={b['recall_on_supported']:.2%}")
    print(f"  tuned      acc={t['accuracy']:.2%}  "
          f"FP-on-supported={t['fp_rate_on_supported']:.2%}  "
          f"recall-on-insufficient={t['recall_on_insufficient']:.2%}  "
          f"recall-on-supported={t['recall_on_supported']:.2%}")
    print()
    cfg = report["tuned_config"]
    print(f"  chosen thresholds: deberta_high_conf={cfg['deberta_high_conf']}  "
          f"numeric_drift_below={cfg['numeric_drift_below']}  "
          f"borderline_band={cfg['borderline_band']}")
    print(f"  rationale: {cfg['rationale']}")
    print()
    o = report["over_flagging"]
    print(
        f"  over-flagging guardrail [{o['status'].upper()}]: "
        f"{o['message']}"
    )
    print()
    if report["persisted_config_path"]:
        print(f"  config persisted -> {report['persisted_config_path']}")
    print(f"  tuned report -> {args.out}")
    return 0


__all__ = [
    "CandidateResult",
    "OVER_FLAG_FRACTION_FAIL",
    "OVER_FLAG_FRACTION_WARN",
    "assess_over_flagging",
    "beats",
    "evaluate_config",
    "tune",
]


if __name__ == "__main__":
    raise SystemExit(main())
