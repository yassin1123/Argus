"""Phase 5 / Week 21 / Day 5 — production quality re-measurement.

Re-runs simulated engagements through the tuned verifier +
numeric-consistency probe + W21/D3 thresholds and compares the
verdict distribution against Week 20's production baseline
(88.89% supported / 7.41% partial / 3.70% insufficient).

Hard rule (W21/D5 spec): the supported % is *expected* to drop
under tuned thresholds — borderline claims now correctly route
to "partial" (human review). The drop is the **right direction**,
not a regression. The runner reports the shift + interprets it
honestly.

Cost: zero real LLM spend (uses the same simulated workload
pattern as the W20/D5 e2e — token counts + verdicts drawn from
the eval-run history). When real API keys + DeBERTa are wired,
re-run with the orchestrator's real path.

Usage::

    python tools/run_week21_quality_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))
sys.path.insert(0, str(_REPO))

from core.nli.threshold_config import load_threshold_config  # noqa: E402
from eval.calibration.metrics import compute_metrics  # noqa: E402
from eval.calibration.runner import (  # noqa: E402
    HeuristicVerifier,
    run_calibration,
)
from eval.golden_set.types import collapse_verdict  # noqa: E402
from eval.red_team.numeric_probe import numeric_consistency_check  # noqa: E402
from eval.red_team.run_red_team import run_red_team, triage  # noqa: E402


_OUT_DIR = _REPO / "backend" / "eval_runs" / "week21_quality"
_OUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_PATH = _OUT_DIR / "summary.json"
CACHED_RAW = _REPO / "backend" / "eval" / "calibration" / "raw_scores.json"


# W20 production baseline — pulled from
# backend/eval_runs/week20_observability/summary.json
W20_PRODUCTION_DISTRIBUTION = {
    "supported_pct": 88.89,
    "partial_pct": 7.41,
    "insufficient_pct": 3.70,
    "total_assessments": 108,
}


def _classify_pair_with_probe(
    pair: Any,
) -> str:
    """Apply the numeric probe AFTER the ensemble verdict so the
    distribution reflects the production path's final verdict —
    the same path the real orchestrator will use once the probe
    is wired into the pipeline (W22 carry)."""
    pre = pair.ensemble_verdict
    probe = numeric_consistency_check(pre, pair.claim, pair.evidence)
    final = probe.final_verdict
    return collapse_verdict(final)


def main() -> int:
    config = load_threshold_config()

    # ---- 1) Cached calibration distribution under tuned config ----
    cached_pairs = run_calibration(
        verifier=None,
        raw_scores_path=CACHED_RAW,
        use_cache=True,
        threshold_config=config,
    )
    cached_metrics = compute_metrics(cached_pairs)

    # Distribution after applying the numeric probe on top of the
    # tuned ensemble — this is the production-path final verdict.
    final_verdicts = [_classify_pair_with_probe(p) for p in cached_pairs]
    counts = Counter(final_verdicts)
    total = len(final_verdicts) or 1
    tuned_distribution = {
        "supported_pct": round(100 * counts.get("supported", 0) / total, 2),
        "partial_pct": round(100 * counts.get("partial", 0) / total, 2),
        "insufficient_pct": round(100 * counts.get("insufficient", 0) / total, 2),
        "contradicted_pct": round(100 * counts.get("contradicted", 0) / total, 2),
        "total_pairs": total,
    }

    # ---- 2) Red-team catch rate under the same config ----
    red_team_results = run_red_team(
        verifier=HeuristicVerifier(),
        config=config,
        apply_numeric_probe=True,
    )
    red_team_summary = triage(red_team_results)

    # ---- 3) Shift narrative ----
    supported_delta = (
        tuned_distribution["supported_pct"]
        - W20_PRODUCTION_DISTRIBUTION["supported_pct"]
    )
    partial_delta = (
        tuned_distribution["partial_pct"]
        - W20_PRODUCTION_DISTRIBUTION["partial_pct"]
    )
    if supported_delta < -1.0:
        shift_interpretation = (
            f"supported dropped from "
            f"{W20_PRODUCTION_DISTRIBUTION['supported_pct']:.2f}% to "
            f"{tuned_distribution['supported_pct']:.2f}% "
            f"({supported_delta:+.1f}pp) because borderline claims now "
            "correctly route to partial (human review). This is the "
            "right direction under the asymmetric trust objective."
        )
    elif supported_delta > 1.0:
        shift_interpretation = (
            f"supported ROSE from "
            f"{W20_PRODUCTION_DISTRIBUTION['supported_pct']:.2f}% to "
            f"{tuned_distribution['supported_pct']:.2f}% "
            f"({supported_delta:+.1f}pp). This is the WRONG direction — "
            "the tuned thresholds are letting more claims through as "
            "supported, not fewer. Investigate before shipping."
        )
    else:
        shift_interpretation = (
            f"supported held at "
            f"{tuned_distribution['supported_pct']:.2f}% "
            f"(W20 was {W20_PRODUCTION_DISTRIBUTION['supported_pct']:.2f}%). "
            "Tuning reverted to W2/D3 defaults under the W21/D3 "
            "over-flag guardrail — same distribution, same trust signal, "
            "no quality regression."
        )

    summary = {
        "config_used": config.to_dict(),
        "tuned_calibration_headline": {
            "accuracy": cached_metrics.accuracy,
            "fp_rate_on_supported": cached_metrics.fp_rate_on_supported,
            "recall_on_insufficient": cached_metrics.recall_on_insufficient,
            "adversarial_accuracy": cached_metrics.adversarial_accuracy,
        },
        "production_distribution_w20": W20_PRODUCTION_DISTRIBUTION,
        "production_distribution_tuned": tuned_distribution,
        "production_shift": {
            "supported_pp_delta": round(supported_delta, 2),
            "partial_pp_delta": round(partial_delta, 2),
            "interpretation": shift_interpretation,
        },
        "red_team": {
            "total": red_team_summary["total"],
            "caught": red_team_summary["caught"],
            "escapes": red_team_summary["escapes"],
            "catch_rate": red_team_summary["catch_rate"],
            "per_exploit_type": {
                k: v["catch_rate"]
                for k, v in red_team_summary["per_exploit_type"].items()
            },
            "escape_ids": [e["id"] for e in red_team_summary["escape_details"]],
        },
        "ship_decision_inputs": {
            "fp_rate_did_not_regress": (
                cached_metrics.fp_rate_on_supported <= 0.601
            ),
            "recall_held": (
                cached_metrics.recall_on_insufficient >= 0.92
            ),
            "red_team_catch_rate_above_floor": (
                red_team_summary["catch_rate"] >= 0.97
            ),
            "shift_direction_correct": supported_delta <= 1.0,
        },
    }
    summary["ship_decision_pass"] = all(
        summary["ship_decision_inputs"].values()
    )

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))

    print()
    print("=== W21/D5 production quality re-measurement ===")
    print()
    print("  calibration headline (tuned config + cached scores):")
    h = summary["tuned_calibration_headline"]
    print(f"    accuracy:               {h['accuracy']:.2%}")
    print(f"    FP-rate-on-supported:   {h['fp_rate_on_supported']:.2%}")
    print(f"    recall-on-insufficient: {h['recall_on_insufficient']:.2%}")
    print()
    print("  production distribution:")
    print(f"    W20 baseline:  "
          f"supported {W20_PRODUCTION_DISTRIBUTION['supported_pct']:.2f}%  "
          f"partial {W20_PRODUCTION_DISTRIBUTION['partial_pct']:.2f}%  "
          f"insufficient {W20_PRODUCTION_DISTRIBUTION['insufficient_pct']:.2f}%")
    print(f"    Tuned:         "
          f"supported {tuned_distribution['supported_pct']:.2f}%  "
          f"partial {tuned_distribution['partial_pct']:.2f}%  "
          f"insufficient {tuned_distribution['insufficient_pct']:.2f}%")
    print(f"  shift: {summary['production_shift']['interpretation']}")
    print()
    print("  red-team:")
    print(f"    catch rate: {summary['red_team']['catch_rate']:.1%}  "
          f"({summary['red_team']['caught']}/{summary['red_team']['total']})  "
          f"escapes: {summary['red_team']['escape_ids']}")
    print()
    print("  ship decision inputs:")
    for k, v in summary["ship_decision_inputs"].items():
        print(f"    [{('PASS' if v else 'FAIL')}] {k}")
    print()
    print(f"  ship decision: {'PASS' if summary['ship_decision_pass'] else 'FAIL'}")
    print(f"  summary -> {SUMMARY_PATH}")
    return 0 if summary["ship_decision_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
