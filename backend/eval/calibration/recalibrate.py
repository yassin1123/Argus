"""Re-calibration + before/after comparison — Phase 5 / Week 22 / Day 4.

The W22/D3 signal fix is in place. This script brings the full
W21 measurement chain forward against the post-fix cached scores
and produces two artifacts:

  - ``post_fix.json`` — the full calibration metrics under the
    new signal (confusion matrix, FP rate, recall, per-category).
  - ``comparison.json`` — the W21 baseline vs W22 post-fix deltas
    across every load-bearing metric, plus the pilot-readiness
    verdict (one of: ready / human_review_required / not_ready).

Zero LLM calls — every number comes from the cached raw scores
(W22/D3 raw_scores.json) and the committed W21/D4 red-team
escapes file.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.nli.threshold_config import load_threshold_config
from eval.calibration.metrics import compute_metrics, split_failures
from eval.calibration.runner import load_scored_pairs
from eval.calibration.tune import (
    OVER_FLAG_FRACTION_FAIL,
    OVER_FLAG_FRACTION_WARN,
    assess_over_flagging,
)

logger = logging.getLogger(__name__)


_BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_RAW = _BACKEND / "eval" / "calibration" / "raw_scores.json"
DEFAULT_RED_TEAM = (
    _BACKEND / "eval_runs" / "week21_red_team" / "escapes.json"
)
POST_FIX_PATH = (
    _BACKEND / "eval_runs" / "week22_recalibration" / "post_fix.json"
)
COMPARISON_PATH = (
    _BACKEND / "eval_runs" / "week22_recalibration" / "comparison.json"
)


# ---------------------------------------------------------------------------
# Frozen W21 numbers (pre-W22/D3 fix). The W21/D2-D5 reports are
# committed; we record the headline values here so the comparison
# is deterministic + doesn't depend on stale baseline.json reads
# after D3 overwrote it.
# ---------------------------------------------------------------------------

W21_BASELINE = {
    "verifier_source": "heuristic_no_keys",
    "accuracy": 0.3167,
    "fp_rate_on_supported": 0.60,
    "recall_on_insufficient": 0.9333,
    "supported_predictions": 5,
    "fp_count_on_supported": 3,
    "supported_review_fraction": 0.8667,    # W21 over-flag fraction
    "over_flag_status": "fail",
    "red_team_catch_rate": 0.9706,
    "red_team_escapes": 1,
    "red_team_escape_ids": ["rt_007"],
}


# ---------------------------------------------------------------------------
# Pilot-readiness verdict
# ---------------------------------------------------------------------------


@dataclass
class PilotReadinessVerdict:
    """One of three honest outcomes per the W22/D4 spec."""

    verdict: str             # ready | human_review_required | not_ready
    headline: str
    rationale: str
    fp_rate_post_fix: float
    over_flag_status: str
    red_team_catch_rate: float
    next_steps: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Thresholds for the verdict mapping:
#   fp_rate ≤ 0.10  AND  over_flag != fail  AND  red_team ≥ 0.95
#       → ready (fully verified pilot positioning)
#   fp_rate ≤ 0.50  AND  over_flag != fail  AND  red_team ≥ 0.85
#       → human_review_required (AI-assisted positioning)
#   otherwise
#       → not_ready (verifier work continues beyond W22)
READY_FP_CEILING = 0.10
HUMAN_REVIEW_FP_CEILING = 0.50
READY_RED_TEAM_FLOOR = 0.95
HUMAN_REVIEW_RED_TEAM_FLOOR = 0.85


def classify_pilot_readiness(
    *,
    fp_rate_post_fix: float,
    over_flag_status: str,
    red_team_catch_rate: float,
) -> PilotReadinessVerdict:
    """Apply the three-way mapping. Honest about which bucket
    the post-fix verifier lands in."""
    if (
        fp_rate_post_fix <= READY_FP_CEILING
        and over_flag_status != "fail"
        and red_team_catch_rate >= READY_RED_TEAM_FLOOR
    ):
        return PilotReadinessVerdict(
            verdict="ready",
            headline="ready_for_pilot_with_documented_bounds",
            rationale=(
                f"FP-rate-on-supported={fp_rate_post_fix:.2%} "
                f"(<= {READY_FP_CEILING:.0%}); red-team "
                f"{red_team_catch_rate:.1%} (>= "
                f"{READY_RED_TEAM_FLOOR:.0%}); over-flag status "
                f"{over_flag_status!r}. The trust claim 'when Argus "
                "says verified, it's right' holds for a pilot with "
                "documented bounds on the known limitations."
            ),
            fp_rate_post_fix=fp_rate_post_fix,
            over_flag_status=over_flag_status,
            red_team_catch_rate=red_team_catch_rate,
            next_steps=[
                "Wire real-ensemble baseline + re-run calibration to "
                "confirm the heuristic-baseline gains carry over.",
                "Pilot with the verifier described as 'verified' (no "
                "human-review qualifier required in messaging).",
                "Continue red-team coverage of the rt_007 / rt_012 "
                "edge cases in Week 23+.",
            ],
        )
    if (
        fp_rate_post_fix <= HUMAN_REVIEW_FP_CEILING
        and over_flag_status != "fail"
        and red_team_catch_rate >= HUMAN_REVIEW_RED_TEAM_FLOOR
    ):
        return PilotReadinessVerdict(
            verdict="human_review_required",
            headline="ai_assisted_with_human_review_required",
            rationale=(
                f"FP-rate-on-supported={fp_rate_post_fix:.2%} is meaningfully "
                f"better than the W21 60% baseline but is above the "
                f"{READY_FP_CEILING:.0%} fully-verified bar. Pilot proceeds "
                "with the verifier framed as 'AI-assisted verification with "
                "human review required on flagged claims' — the honest "
                "positioning the W22/D4 spec calls out as the middle outcome. "
                f"Red-team holds at {red_team_catch_rate:.1%}; over-flag "
                f"status {over_flag_status!r}."
            ),
            fp_rate_post_fix=fp_rate_post_fix,
            over_flag_status=over_flag_status,
            red_team_catch_rate=red_team_catch_rate,
            next_steps=[
                "Pilot copy + UI: rename 'verified' to 'AI-verified, "
                "human-reviewable'. Every supported claim carries a "
                "review-recommended affordance.",
                "Real-ensemble baseline + re-run is the next quality "
                "lever; budget ~$2-3.",
                "Track FP rate in production via the W21/D5 dashboard "
                "panel — set an alert at 50% (HUMAN_REVIEW_FP_CEILING).",
            ],
        )
    return PilotReadinessVerdict(
        verdict="not_ready",
        headline="verifier_work_continues_beyond_w22",
        rationale=(
            f"FP-rate-on-supported={fp_rate_post_fix:.2%}, red-team "
            f"{red_team_catch_rate:.1%}, over-flag status "
            f"{over_flag_status!r}. The verifier is below the "
            "human-review-acceptable bar. Pilot scope or messaging "
            "must adjust; verifier work continues."
        ),
        fp_rate_post_fix=fp_rate_post_fix,
        over_flag_status=over_flag_status,
        red_team_catch_rate=red_team_catch_rate,
        next_steps=[
            "Continue verifier work into Week 23. The bottleneck per "
            "W22/D2 diagnosis is multi-front; the W22/D3 fix targeted "
            "the LLM judge — next leverage targets are evidence "
            "selection and DeBERTa replacement.",
            "Don't ship the pilot with 'verified' messaging.",
        ],
    )


# ---------------------------------------------------------------------------
# Recalibration runner
# ---------------------------------------------------------------------------


def recalibrate(raw_path: Path | None = None) -> dict[str, Any]:
    """Compute the full calibration metrics + over-flag panel +
    failure-case breakdown from the cached post-fix raw scores."""
    rp = raw_path or DEFAULT_RAW
    if not rp.exists():
        raise FileNotFoundError(f"raw scores missing at {rp}")
    pairs = load_scored_pairs(rp)
    metrics = compute_metrics(pairs)
    failures = split_failures(pairs)
    over_flag = assess_over_flagging(metrics.to_dict())
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "verifier_source": "heuristic_no_keys",
        "config_used": load_threshold_config().to_dict(),
        "headline": {
            "accuracy": metrics.accuracy,
            "fp_rate_on_supported": metrics.fp_rate_on_supported,
            "recall_on_insufficient": metrics.recall_on_insufficient,
            "adversarial_accuracy": metrics.adversarial_accuracy,
        },
        "metrics": metrics.to_dict(),
        "over_flagging": over_flag,
        "failure_cases": failures,
    }


def _load_red_team_post_fix(
    path: Path | None = None,
) -> dict[str, Any]:
    """Read the committed W21/D4 escapes.json — which was
    regenerated by the W22/D3 fix-run. Returns headline summary
    only; the per-pair detail stays in the original file."""
    p = path or DEFAULT_RED_TEAM
    if not p.exists():
        return {
            "catch_rate": None,
            "escapes": None,
            "escape_ids": [],
            "per_exploit_type": {},
        }
    doc = json.loads(p.read_text())
    summary = doc.get("summary") or {}
    return {
        "catch_rate": summary.get("catch_rate"),
        "caught": summary.get("caught"),
        "total": summary.get("total"),
        "escapes": summary.get("escapes"),
        "escape_ids": [
            e.get("id") for e in summary.get("escape_details") or []
        ],
        "per_exploit_type": {
            k: {
                "catch_rate": v["catch_rate"],
                "caught": v["caught"],
                "total": v["total"],
            }
            for k, v in (summary.get("per_exploit_type") or {}).items()
        },
    }


def build_comparison(post_fix: dict[str, Any]) -> dict[str, Any]:
    """Produce the W21 → W22 before/after comparison + the pilot
    readiness verdict."""
    h = post_fix["headline"]
    of = post_fix["over_flagging"]
    rt = _load_red_team_post_fix()

    verdict = classify_pilot_readiness(
        fp_rate_post_fix=float(h["fp_rate_on_supported"]),
        over_flag_status=str(of["status"]),
        red_team_catch_rate=float(rt["catch_rate"] or 0.0),
    )

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "verifier_source": post_fix["verifier_source"],
        "w21_baseline": W21_BASELINE,
        "w22_post_fix": {
            "accuracy": h["accuracy"],
            "fp_rate_on_supported": h["fp_rate_on_supported"],
            "recall_on_insufficient": h["recall_on_insufficient"],
            "adversarial_accuracy": h["adversarial_accuracy"],
            "supported_predictions": post_fix["metrics"]["supported_predictions"],
            "fp_count_on_supported": post_fix["metrics"]["fp_count_on_supported"],
            "supported_review_fraction": of["supported_review_fraction"],
            "over_flag_status": of["status"],
            "red_team_catch_rate": rt["catch_rate"],
            "red_team_escapes": rt["escapes"],
            "red_team_escape_ids": rt["escape_ids"],
        },
        "deltas": {
            "fp_rate_on_supported_pp": round(
                100 * (h["fp_rate_on_supported"]
                       - W21_BASELINE["fp_rate_on_supported"]), 2,
            ),
            "recall_on_insufficient_pp": round(
                100 * (h["recall_on_insufficient"]
                       - W21_BASELINE["recall_on_insufficient"]), 2,
            ),
            "accuracy_pp": round(
                100 * (h["accuracy"] - W21_BASELINE["accuracy"]), 2,
            ),
            "supported_review_fraction_pp": round(
                100 * (of["supported_review_fraction"]
                       - W21_BASELINE["supported_review_fraction"]), 2,
            ),
            "red_team_catch_rate_pp": round(
                100 * ((rt["catch_rate"] or 0)
                       - W21_BASELINE["red_team_catch_rate"]), 2,
            ),
        },
        "red_team_per_exploit": rt["per_exploit_type"],
        "pilot_readiness": verdict.to_dict(),
    }


def write_all(
    *,
    raw_path: Path | None = None,
    post_fix_out: Path | None = None,
    comparison_out: Path | None = None,
) -> dict[str, Any]:
    post_fix = recalibrate(raw_path)
    comparison = build_comparison(post_fix)
    out_a = post_fix_out or POST_FIX_PATH
    out_b = comparison_out or COMPARISON_PATH
    out_a.parent.mkdir(parents=True, exist_ok=True)
    out_b.parent.mkdir(parents=True, exist_ok=True)
    out_a.write_text(json.dumps(post_fix, indent=2))
    out_b.write_text(json.dumps(comparison, indent=2))
    return comparison


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default=str(DEFAULT_RAW))
    ap.add_argument("--out", default=str(POST_FIX_PATH))
    ap.add_argument("--compare-out", default=str(COMPARISON_PATH))
    args = ap.parse_args(argv)

    comparison = write_all(
        raw_path=Path(args.raw),
        post_fix_out=Path(args.out),
        comparison_out=Path(args.compare_out),
    )

    pf = comparison["w22_post_fix"]
    d = comparison["deltas"]
    print()
    print("=== W22/D4 re-calibration + before/after ===")
    print()
    print("  W21 baseline (pre-fix):")
    b = comparison["w21_baseline"]
    print(f"    FP-rate-on-supported:      {b['fp_rate_on_supported']:.2%}")
    print(f"    recall-on-insufficient:    {b['recall_on_insufficient']:.2%}")
    print(f"    over-flag fraction:        {b['supported_review_fraction']:.2%} "
          f"[{b['over_flag_status'].upper()}]")
    print(f"    red-team catch rate:       {b['red_team_catch_rate']:.2%}")
    print()
    print("  W22 post-fix:")
    print(f"    FP-rate-on-supported:      {pf['fp_rate_on_supported']:.2%}  "
          f"(delta {d['fp_rate_on_supported_pp']:+.2f}pp)")
    print(f"    recall-on-insufficient:    {pf['recall_on_insufficient']:.2%}  "
          f"(delta {d['recall_on_insufficient_pp']:+.2f}pp)")
    print(f"    over-flag fraction:        {pf['supported_review_fraction']:.2%} "
          f"[{pf['over_flag_status'].upper()}]  "
          f"(delta {d['supported_review_fraction_pp']:+.2f}pp)")
    if pf["red_team_catch_rate"] is not None:
        print(f"    red-team catch rate:       {pf['red_team_catch_rate']:.2%}  "
              f"(delta {d['red_team_catch_rate_pp']:+.2f}pp)")
    print()
    v = comparison["pilot_readiness"]
    print(f"  PILOT-READINESS VERDICT: {v['verdict'].upper()}")
    print(f"  {v['rationale']}")
    print()
    print(f"  post_fix      -> {args.out}")
    print(f"  comparison    -> {args.compare_out}")
    return 0


__all__ = [
    "HUMAN_REVIEW_FP_CEILING",
    "HUMAN_REVIEW_RED_TEAM_FLOOR",
    "PilotReadinessVerdict",
    "READY_FP_CEILING",
    "READY_RED_TEAM_FLOOR",
    "W21_BASELINE",
    "build_comparison",
    "classify_pilot_readiness",
    "recalibrate",
    "write_all",
]


if __name__ == "__main__":
    raise SystemExit(main())
