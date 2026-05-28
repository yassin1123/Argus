"""W24/D1 real-claim calibration gate + pilot-go/no-go verdict.

Phase 5 / Week 24 / Day 1. This is the gate that's been deferred
since Week 22: run the labelled real-claim batch through the REAL
cross-family verifier and produce the pilot go/no-go decision on
verifier quality.

Two outputs:

  - ``backend/eval_runs/week24_real_calibration/summary.json``
    — the calibration metrics: real FP-rate-on-supported,
    recall-on-insufficient, recall-on-supported, per-category
    accuracy, confusion matrix, failure cases.
  - ``backend/eval_runs/week24_real_calibration/pilot_verdict.json``
    — the explicit GREEN / YELLOW / RED verdict with the measured
    FP rate, the resulting pilot posture, and the recall safety
    check.

Pilot thresholds (W24/D1 spec) against the measured real
FP-rate-on-supported:

  - GREEN  (≤ 5%):   pilot proceeds with full "verified" posture.
  - YELLOW (5-15%):  pilot proceeds with "AI-assisted verification
                     with human review on flagged claims" — an
                     honest, shippable posture (NOT a failure).
  - RED    (> 15%):  pilot does NOT start this week; Week 24 pivots
                     to verifier work.

Safety property: recall-on-insufficient (the catch rate for
unsupported claims) must remain ≥ 0.85 regardless of the FP band.
A recall below the floor downgrades the posture even when the FP
rate is green — a verifier that misses unsupported claims is a
trust hazard.

Hard rules (W24/D1 + carried from W22/D1):
  - Real ground truth is human-labelled, never LLM-labelled. This
    runner CONSUMES labels from ``tools/label_claims.py``; it never
    produces them.
  - ≥40 labelled pairs required for a gate decision. Below that the
    statistical signal is too weak — the runner refuses and writes
    an ``insufficient_labels`` verdict rather than a number that
    looks real.
  - The verifier_source is recorded precisely. ``cross_family_llm``
    requires keys AND DeBERTa present; the W22 gate-check enforces
    this. We never label a degraded run ``cross_family_llm``.

Usage::

    python backend/eval/calibration/run_calibration.py \\
        --set real --verifier cross_family_llm
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv  # noqa: E402

_REPO_ROOT = _BACKEND.parent
load_dotenv(_REPO_ROOT / ".env")

from eval.calibration.fix_day import RealLLMVerifier, check_gate  # noqa: E402
from eval.calibration.metrics import compute_metrics, split_failures  # noqa: E402
from eval.calibration.runner import run_calibration  # noqa: E402
from eval.golden_set import GoldenSet  # noqa: E402
from eval.golden_set.loader import load_real_run_entries  # noqa: E402

logger = logging.getLogger(__name__)


OUT_DIR = _BACKEND / "eval_runs" / "week24_real_calibration"
SUMMARY_PATH = OUT_DIR / "summary.json"
VERDICT_PATH = OUT_DIR / "pilot_verdict.json"
RAW_REAL = _BACKEND / "eval" / "calibration" / "raw_scores_w24_real.json"


# ---------------------------------------------------------------------------
# Gate constants — W24/D1 pilot thresholds
# ---------------------------------------------------------------------------

MIN_LABELLED_PAIRS = 40
GREEN_FP_CEILING = 0.05
YELLOW_FP_CEILING = 0.15
RECALL_ON_INSUFFICIENT_FLOOR = 0.85

# Spend backstop: 53 pairs × ~$0.04 ≈ $2; cap pairs so a runaway
# can't blow the ~$4 budget the spec set.
MAX_PAIRS_DEFAULT = 80


# ---------------------------------------------------------------------------
# Verdict shape
# ---------------------------------------------------------------------------


@dataclass
class PilotVerdict:
    """The explicit pilot go/no-go on verifier quality."""

    band: str                       # GREEN | YELLOW | RED
    proceeds: bool                  # does the pilot start this week?
    posture: str                    # the user-facing trust posture
    real_fp_rate_on_supported: float
    real_recall_on_insufficient: float
    recall_safety_ok: bool
    real_pair_count: int
    verifier_source: str
    rationale: str
    drives_week_24: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_pilot_verdict(
    *,
    fp_rate: float,
    recall_on_insufficient: float,
    pair_count: int,
    verifier_source: str,
) -> PilotVerdict:
    """Apply the W24/D1 thresholds. Pure function — no I/O — so the
    test suite can assert the band boundaries directly."""
    recall_ok = recall_on_insufficient >= RECALL_ON_INSUFFICIENT_FLOOR

    if fp_rate <= GREEN_FP_CEILING:
        band = "GREEN"
    elif fp_rate <= YELLOW_FP_CEILING:
        band = "YELLOW"
    else:
        band = "RED"

    # The FP band sets the baseline disposition; the recall safety
    # check can downgrade it. A green FP rate with a broken catch
    # rate is NOT a clean pilot.
    if band == "RED":
        proceeds = False
        posture = "pilot_blocked_verifier_work_required"
        rationale = (
            f"Real FP-rate-on-supported = {fp_rate:.1%} exceeds the "
            f"{YELLOW_FP_CEILING:.0%} RED threshold. More than one in "
            "six 'supported' verdicts is wrong on real claims — the "
            "trust wedge is not defensible. The pilot does NOT start "
            "this week."
        )
        drives = (
            "Week 24 PIVOTS to verifier work (retrieval quality, prompt "
            "tightening, additional probes); the pilot date moves. "
            "Days 2-5 become verifier days."
        )
    elif not recall_ok:
        # FP is green/yellow but the safety property is broken.
        proceeds = False
        posture = "pilot_blocked_safety_floor_breached"
        rationale = (
            f"Real FP-rate-on-supported = {fp_rate:.1%} (band {band}), "
            f"but recall-on-insufficient = {recall_on_insufficient:.1%} "
            f"is below the {RECALL_ON_INSUFFICIENT_FLOOR:.0%} safety "
            "floor. The verifier passes too many genuinely-unsupported "
            "claims; the catch-rate property that protects the wedge is "
            "broken. The pilot does NOT start until the catch rate "
            "recovers."
        )
        drives = (
            "Week 24 PIVOTS to recall recovery (lower the supported "
            "threshold / strengthen the insufficient detectors) before "
            "the pilot can start."
        )
    elif band == "GREEN":
        proceeds = True
        posture = "verified"
        rationale = (
            f"Real FP-rate-on-supported = {fp_rate:.1%}, ≤ the "
            f"{GREEN_FP_CEILING:.0%} GREEN threshold, AND recall-on-"
            f"insufficient = {recall_on_insufficient:.1%} ≥ the "
            f"{RECALL_ON_INSUFFICIENT_FLOOR:.0%} safety floor. The "
            "verifier is pilot-grade on real claims."
        )
        drives = (
            "Pilot proceeds with the full 'verified' posture. Days 2-5 "
            "run the pilot-readiness track (onboarding, runbooks, dry "
            "run)."
        )
    else:  # YELLOW
        proceeds = True
        posture = "ai_assisted_human_review"
        rationale = (
            f"Real FP-rate-on-supported = {fp_rate:.1%}, in the "
            f"{GREEN_FP_CEILING:.0%}-{YELLOW_FP_CEILING:.0%} YELLOW "
            f"band, with recall-on-insufficient = "
            f"{recall_on_insufficient:.1%} ≥ the "
            f"{RECALL_ON_INSUFFICIENT_FLOOR:.0%} safety floor. This is a "
            "successful gate-pass: 'AI-assisted verification with human "
            "review on flagged claims' is an honest, valuable, "
            "shippable pilot posture."
        )
        drives = (
            "Pilot proceeds with the 'AI-assisted with human review' "
            "posture (already in place from W22). Days 2-5 run the "
            "pilot-readiness track."
        )

    return PilotVerdict(
        band=band,
        proceeds=proceeds,
        posture=posture,
        real_fp_rate_on_supported=round(fp_rate, 4),
        real_recall_on_insufficient=round(recall_on_insufficient, 4),
        recall_safety_ok=recall_ok,
        real_pair_count=pair_count,
        verifier_source=verifier_source,
        rationale=rationale,
        drives_week_24=drives,
    )


# ---------------------------------------------------------------------------
# Real batch loader
# ---------------------------------------------------------------------------


def _load_real_batch() -> GoldenSet:
    """Load the human-labelled real-claim fixtures from
    ``real_runs/``. Filters to ``evidence_source == 'real_run'`` so
    a stray synthetic seed can't inflate the count."""
    entries = load_real_run_entries()
    entries = [e for e in entries if e.evidence_source == "real_run"]
    return GoldenSet(entries=entries)


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def run_real_calibration_gate(
    *,
    requested_verifier: str = "cross_family_llm",
    max_pairs: int | None = None,
    raw_path: Path | None = None,
    summary_path: Path | None = None,
    verdict_path: Path | None = None,
) -> dict[str, Any]:
    """Run the W24/D1 gate end-to-end. Writes summary.json +
    pilot_verdict.json and returns the summary dict."""
    raw_path = raw_path or RAW_REAL
    summary_path = summary_path or SUMMARY_PATH
    verdict_path = verdict_path or VERDICT_PATH
    max_pairs = max_pairs or MAX_PAIRS_DEFAULT

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- gate check: keys + DeBERTa ---
    gate = check_gate()
    if gate.blocked:
        summary = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "gate_status": "blocked",
            "verifier_source": "blocked",
            "gate_check": gate.to_dict(),
            "real_pair_count": 0,
            "real_metrics": None,
        }
        summary_path.write_text(json.dumps(summary, indent=2))
        verdict = {
            "generated_at": summary["generated_at"],
            "band": "BLOCKED",
            "proceeds": False,
            "posture": "pilot_blocked_no_verifier",
            "rationale": (
                "Cross-family verifier unavailable: "
                + "; ".join(gate.blockers)
            ),
        }
        verdict_path.write_text(json.dumps(verdict, indent=2))
        return summary

    # The spec asks for cross_family_llm; refuse to mislabel a
    # degraded run. If the user asked for the full ensemble but
    # DeBERTa is absent, the gate's chosen source is
    # real_llm_no_deberta — fail loud rather than claim the name.
    if (
        requested_verifier == "cross_family_llm"
        and gate.chosen_verifier_source != "cross_family_llm"
    ):
        summary = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "gate_status": "degraded_verifier_refused",
            "verifier_source": gate.chosen_verifier_source,
            "gate_check": gate.to_dict(),
            "real_pair_count": 0,
            "real_metrics": None,
        }
        summary_path.write_text(json.dumps(summary, indent=2))
        verdict = {
            "generated_at": summary["generated_at"],
            "band": "BLOCKED",
            "proceeds": False,
            "posture": "pilot_blocked_degraded_verifier",
            "rationale": (
                "Requested cross_family_llm but DeBERTa is absent; the "
                "gate would only produce 'real_llm_no_deberta'. Refusing "
                "to mislabel a degraded run as the full ensemble. Install "
                "sentence-transformers, then re-run."
            ),
        }
        verdict_path.write_text(json.dumps(verdict, indent=2))
        return summary

    verifier_source = gate.chosen_verifier_source

    # --- load labelled batch + enforce the floor ---
    real = _load_real_batch()
    real_count = len(real)
    if real_count < MIN_LABELLED_PAIRS:
        summary = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "gate_status": "insufficient_labels",
            "verifier_source": verifier_source,
            "real_pair_count": real_count,
            "real_metrics": None,
            "min_required": MIN_LABELLED_PAIRS,
        }
        summary_path.write_text(json.dumps(summary, indent=2))
        verdict = {
            "generated_at": summary["generated_at"],
            "band": "INSUFFICIENT_LABELS",
            "proceeds": False,
            "posture": "pilot_blocked_insufficient_labels",
            "real_pair_count": real_count,
            "min_required": MIN_LABELLED_PAIRS,
            "rationale": (
                f"Only {real_count} labelled real-claim pairs; the gate "
                f"needs ≥{MIN_LABELLED_PAIRS} for a statistically "
                "meaningful FP rate. Label more pairs "
                "(tools/label_claims.py), then re-run."
            ),
        }
        verdict_path.write_text(json.dumps(verdict, indent=2))
        return summary

    # --- run the real cross-family verifier ---
    verifier = RealLLMVerifier(name=verifier_source)
    pairs = run_calibration(
        verifier=verifier,
        golden_set=real,
        raw_scores_path=raw_path,
        use_cache=False,
        max_pairs=max_pairs,
    )
    metrics = compute_metrics(pairs)
    failures = split_failures(pairs)

    # recall-on-supported, for the report (catch rate the other way)
    per_class = {c.label: c for c in metrics.per_class}
    recall_on_supported = (
        per_class["supported"].recall if "supported" in per_class else 0.0
    )

    summary = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "gate_status": "complete",
        "verifier_source": verifier.name,
        "real_pair_count": len(pairs),
        "real_metrics": metrics.to_dict(),
        "headline": {
            "fp_rate_on_supported": metrics.fp_rate_on_supported,
            "recall_on_insufficient": metrics.recall_on_insufficient,
            "recall_on_supported": recall_on_supported,
            "accuracy": metrics.accuracy,
        },
        "confusion_matrix": metrics.confusion,
        "per_category_accuracy": metrics.per_category_accuracy,
        "per_category_pair_count": metrics.per_category_pair_count,
        "failure_cases": failures,
    }
    summary_path.write_text(json.dumps(summary, indent=2))

    # --- the pilot verdict ---
    verdict_obj = classify_pilot_verdict(
        fp_rate=metrics.fp_rate_on_supported,
        recall_on_insufficient=metrics.recall_on_insufficient,
        pair_count=len(pairs),
        verifier_source=verifier.name,
    )
    verdict_full = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        **verdict_obj.to_dict(),
        "thresholds": {
            "green_fp_ceiling": GREEN_FP_CEILING,
            "yellow_fp_ceiling": YELLOW_FP_CEILING,
            "recall_on_insufficient_floor": RECALL_ON_INSUFFICIENT_FLOOR,
            "min_labelled_pairs": MIN_LABELLED_PAIRS,
        },
        "supporting_metrics": {
            "recall_on_supported": recall_on_supported,
            "accuracy": metrics.accuracy,
            "supported_predictions": metrics.supported_predictions,
            "fp_count_on_supported": metrics.fp_count_on_supported,
            "insufficient_total": metrics.insufficient_total,
            "insufficient_caught": metrics.insufficient_caught,
        },
    }
    verdict_path.write_text(json.dumps(verdict_full, indent=2))

    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--set", dest="set_name", choices=["real"], default="real",
        help="W24/D1 runs the real labelled set.",
    )
    ap.add_argument(
        "--verifier", default="cross_family_llm",
        choices=["cross_family_llm", "real_llm_no_deberta"],
        help="Verifier source. cross_family_llm = full 3-signal "
             "ensemble (requires keys + DeBERTa).",
    )
    ap.add_argument(
        "--max-pairs", type=int, default=MAX_PAIRS_DEFAULT,
        help=f"Spend cap on pairs scored (default {MAX_PAIRS_DEFAULT}).",
    )
    args = ap.parse_args(argv)

    summary = run_real_calibration_gate(
        requested_verifier=args.verifier,
        max_pairs=args.max_pairs,
    )

    print()
    print("=== W24/D1 real-claim calibration gate ===")
    print(f"  gate_status:    {summary['gate_status']}")
    print(f"  verifier_source:{summary['verifier_source']}")
    print(f"  real pairs:     {summary['real_pair_count']}")
    if summary.get("real_metrics"):
        h = summary["headline"]
        print(f"  FP-rate-on-supported:   {h['fp_rate_on_supported']:.2%}")
        print(f"  recall-on-insufficient: {h['recall_on_insufficient']:.2%}")
        print(f"  recall-on-supported:    {h['recall_on_supported']:.2%}")
        print(f"  accuracy:               {h['accuracy']:.2%}")
        if VERDICT_PATH.exists():
            v = json.loads(VERDICT_PATH.read_text(encoding="utf-8"))
            print()
            print(f"  PILOT VERDICT: {v['band']}  (proceeds={v['proceeds']})")
            print(f"  posture: {v['posture']}")
            print(f"  {v['rationale']}")
            print(f"  -> {v['drives_week_24']}")
    else:
        print(f"  (no metrics — see verdict for why)")
    print()
    print(f"  summary -> {SUMMARY_PATH}")
    print(f"  verdict -> {VERDICT_PATH}")
    return 0


__all__ = [
    "GREEN_FP_CEILING",
    "MIN_LABELLED_PAIRS",
    "PilotVerdict",
    "RECALL_ON_INSUFFICIENT_FLOOR",
    "YELLOW_FP_CEILING",
    "classify_pilot_verdict",
    "run_real_calibration_gate",
]


if __name__ == "__main__":
    raise SystemExit(main())
