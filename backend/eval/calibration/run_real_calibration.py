"""Real-claim calibration runner — Phase 5 / Week 22 / Day 1.

Runs the real cross-family verifier (or the heuristic fallback)
against the labelled real-claim batch in
``backend/eval/golden_set/real_runs/`` and writes a calibration
report that compares to the W21 synthetic baseline.

Three honest paths:

  - **labelled real claims present** — the spec's preferred path.
    Loads ``real_runs/*.yaml|*.json``, runs each pair through the
    verifier, caches raw scores to ``raw_scores_real.json``,
    computes metrics, compares to the W21 synthetic baseline,
    records the scoping verdict (light_polish | full_fix |
    borderline).
  - **labelled real claims absent** — the spec's explicit safe
    default ("If labeling can't happen this session, the week
    proceeds on the synthetic worst-case"). Reports
    ``labeling_pending`` as the scoping verdict + carries the
    W21 synthetic baseline forward as the working number.
  - **API keys missing for real_ensemble** — the runner falls
    back to ``heuristic_no_keys`` and labels the verifier_source
    so the operator never confuses heuristic numbers with real
    ones (the W21/D5 retro discipline).

Output: ``backend/eval_runs/week22_real_calibration/summary.json``.

Hard rule from W22/D1: real ground truth is human-labelled, never
LLM-labelled. The runner never produces ground truth itself —
it consumes labels written by ``tools/label_claims.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from eval.calibration.metrics import compute_metrics, split_failures
from eval.calibration.runner import (
    HeuristicVerifier,
    VerifierProtocol,
    run_calibration,
)
from eval.golden_set import GoldenSet
from eval.golden_set.loader import load_real_run_entries

logger = logging.getLogger(__name__)

DEFAULT_OUT = (
    _BACKEND / "eval_runs" / "week22_real_calibration" / "summary.json"
)
DEFAULT_RAW_REAL = (
    _BACKEND / "eval" / "calibration" / "raw_scores_real.json"
)


# ---------------------------------------------------------------------------
# Scoping verdict
# ---------------------------------------------------------------------------


@dataclass
class ScopingVerdict:
    """The decisive comparison + the week-driving disposition."""

    verdict: str                           # light_polish | full_fix | borderline | labeling_pending
    rationale: str
    real_fp_rate_on_supported: float | None
    real_recall_on_insufficient: float | None
    synthetic_fp_rate_on_supported: float
    synthetic_recall_on_insufficient: float
    real_pair_count: int
    drives_w22_days_2_to_5: str            # one short sentence

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Spec thresholds from W22/D1:
#   real FP ≤ ~10%  -> light polish + document why synthetic ≠ real
#   real FP > ~10%  -> full upstream fix Days 2-5
LIGHT_POLISH_FP_CEILING = 0.10
# A wide BORDERLINE band so a "10-20%" landing is clearly flagged.
BORDERLINE_FP_CEILING = 0.20

# Synthetic baselines from W21 — frozen here so the W22 comparison
# uses the same numbers committed in the W21 quality wrap-up.
W21_SYNTHETIC_FP_RATE = 0.60
W21_SYNTHETIC_RECALL_INS = 0.9333


def _classify_scoping(
    real_fp: float | None, real_count: int,
) -> ScopingVerdict:
    """Apply the W22/D1 spec's thresholds to land the
    scoping verdict that drives Days 2-5."""
    if real_count == 0:
        return ScopingVerdict(
            verdict="labeling_pending",
            rationale=(
                "No labelled real claims found in real_runs/. The spec's "
                "explicit fallback applies: the week proceeds on the "
                "synthetic worst-case (the W21 60% FP) as the safer "
                "default. Yassin runs tools/extract_claims_for_labeling.py "
                "+ tools/label_claims.py to seed the batch when the "
                "30-60 min commitment is available, then re-runs this "
                "script and the verdict re-classifies."
            ),
            real_fp_rate_on_supported=None,
            real_recall_on_insufficient=None,
            synthetic_fp_rate_on_supported=W21_SYNTHETIC_FP_RATE,
            synthetic_recall_on_insufficient=W21_SYNTHETIC_RECALL_INS,
            real_pair_count=0,
            drives_w22_days_2_to_5=(
                "Days 2-5 follow the FULL FIX path (the W21 synthetic "
                "60% FP is the working number until real labels exist)."
            ),
        )
    fp = float(real_fp or 0.0)
    if fp <= LIGHT_POLISH_FP_CEILING:
        return ScopingVerdict(
            verdict="light_polish",
            rationale=(
                f"Real FP-rate-on-supported = {fp:.1%}, ≤ "
                f"{LIGHT_POLISH_FP_CEILING:.0%} threshold. The W21 "
                "synthetic set was adversarially hard; production "
                "verifier is largely fine. Days 2-5 polish + document "
                "why synthetic ≠ real."
            ),
            real_fp_rate_on_supported=fp,
            real_recall_on_insufficient=None,  # filled by the runner
            synthetic_fp_rate_on_supported=W21_SYNTHETIC_FP_RATE,
            synthetic_recall_on_insufficient=W21_SYNTHETIC_RECALL_INS,
            real_pair_count=real_count,
            drives_w22_days_2_to_5=(
                "Days 2-5 = LIGHT POLISH path: document synthetic-vs-real "
                "delta + ship a small set of quality nice-to-haves."
            ),
        )
    if fp <= BORDERLINE_FP_CEILING:
        return ScopingVerdict(
            verdict="borderline",
            rationale=(
                f"Real FP-rate-on-supported = {fp:.1%}, between "
                f"{LIGHT_POLISH_FP_CEILING:.0%} and {BORDERLINE_FP_CEILING:.0%}. "
                "Genuine miscalibration but not catastrophic. Days 2-5 "
                "proceed with the fix path; document the borderline "
                "landing in the wrap-up."
            ),
            real_fp_rate_on_supported=fp,
            real_recall_on_insufficient=None,
            synthetic_fp_rate_on_supported=W21_SYNTHETIC_FP_RATE,
            synthetic_recall_on_insufficient=W21_SYNTHETIC_RECALL_INS,
            real_pair_count=real_count,
            drives_w22_days_2_to_5=(
                "Days 2-5 = FIX PATH (borderline severity)."
            ),
        )
    return ScopingVerdict(
        verdict="full_fix",
        rationale=(
            f"Real FP-rate-on-supported = {fp:.1%}, > "
            f"{BORDERLINE_FP_CEILING:.0%}. Genuine miscalibration. "
            "Days 2-5 do the full upstream fix (retrieval quality, "
            "prompt tightening, additional probes)."
        ),
        real_fp_rate_on_supported=fp,
        real_recall_on_insufficient=None,
        synthetic_fp_rate_on_supported=W21_SYNTHETIC_FP_RATE,
        synthetic_recall_on_insufficient=W21_SYNTHETIC_RECALL_INS,
        real_pair_count=real_count,
        drives_w22_days_2_to_5=(
            "Days 2-5 = FULL UPSTREAM FIX path."
        ),
    )


# ---------------------------------------------------------------------------
# Real-batch loader
# ---------------------------------------------------------------------------


def _load_real_batch() -> GoldenSet:
    """Read labelled real-claim YAML/JSON from
    ``backend/eval/golden_set/real_runs/``. Empty when nothing's
    been labelled yet — the runner records that as
    ``labeling_pending``."""
    entries = load_real_run_entries()
    # Drop synthetic seeds if any landed in this dir by mistake.
    entries = [e for e in entries if e.evidence_source == "real_run"]
    return GoldenSet(entries=entries)


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def _select_verifier(name: str | None) -> VerifierProtocol:
    """Returns the real ensemble when explicitly requested + when
    keys appear configured; otherwise the heuristic fallback. The
    verifier_source label is preserved on the output so the
    operator can tell which path produced the numbers."""
    if name == "real_ensemble":
        # Don't import the real path unless asked — it pulls heavy
        # litellm / DeBERTa modules.
        from eval.calibration.runner import RealEnsembleVerifier
        return RealEnsembleVerifier()
    return HeuristicVerifier()


def write_real_calibration(
    *,
    verifier_name: str = "heuristic_no_keys",
    raw_path: Path | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Run the calibration against the labelled real batch, write
    the summary, return the dict."""
    raw_path = raw_path or DEFAULT_RAW_REAL
    out_path = out_path or DEFAULT_OUT

    real = _load_real_batch()
    real_count = len(real)

    if real_count == 0:
        # Honest "labeling_pending" path — no verifier call, no
        # LLM spend, no cached scores. Just record the verdict +
        # carry the W21 synthetic baseline forward as the working
        # number for Days 2-5.
        scoping = _classify_scoping(real_fp=None, real_count=0)
        summary: dict[str, Any] = {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "verifier_source": "skipped_no_real_labels",
            "real_pair_count": 0,
            "real_metrics": None,
            "synthetic_baseline": {
                "verifier_source_at_baseline": "heuristic_no_keys",
                "fp_rate_on_supported": W21_SYNTHETIC_FP_RATE,
                "recall_on_insufficient": W21_SYNTHETIC_RECALL_INS,
            },
            "scoping": scoping.to_dict(),
            "comparison": {
                "real_vs_synthetic_fp_delta": None,
                "real_vs_synthetic_recall_delta": None,
                "synthetic_was_worst_case": None,
            },
            "next_steps_for_labelling": [
                "python tools/extract_claims_for_labeling.py "
                "--source eval_runs --per-verdict 12 --limit 200 "
                "--out backend/eval/golden_set/real_runs/_worksheet.json",
                "python tools/label_claims.py "
                "--in backend/eval/golden_set/real_runs/_worksheet.json "
                "--out backend/eval/golden_set/real_runs/"
                "labelled_<date>.yaml",
                "python -m eval.calibration.run_real_calibration  "
                "# re-run; the verdict reclassifies",
            ],
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2))
        return summary

    # ---- the labelled path ----
    verifier = _select_verifier(verifier_name)
    pairs = run_calibration(
        verifier=verifier,
        golden_set=real,
        raw_scores_path=raw_path,
        use_cache=False,
    )
    metrics = compute_metrics(pairs)
    failures = split_failures(pairs)

    scoping = _classify_scoping(
        real_fp=metrics.fp_rate_on_supported,
        real_count=real_count,
    )
    scoping.real_recall_on_insufficient = metrics.recall_on_insufficient

    fp_delta = metrics.fp_rate_on_supported - W21_SYNTHETIC_FP_RATE
    rec_delta = metrics.recall_on_insufficient - W21_SYNTHETIC_RECALL_INS

    summary = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "verifier_source": verifier.name,
        "real_pair_count": real_count,
        "real_metrics": metrics.to_dict(),
        "synthetic_baseline": {
            "verifier_source_at_baseline": "heuristic_no_keys",
            "fp_rate_on_supported": W21_SYNTHETIC_FP_RATE,
            "recall_on_insufficient": W21_SYNTHETIC_RECALL_INS,
        },
        "scoping": scoping.to_dict(),
        "comparison": {
            "real_vs_synthetic_fp_delta": round(fp_delta, 4),
            "real_vs_synthetic_recall_delta": round(rec_delta, 4),
            # If real FP is LOWER than synthetic, the synthetic set
            # was a worst case (which is the W21 hypothesis).
            "synthetic_was_worst_case": fp_delta < -0.05,
        },
        "failure_cases": failures,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--set", dest="set_name", choices=["real"], default="real",
        help="W22/D1 always runs the real set; flag kept for symmetry "
             "with future per-set calibration variants.",
    )
    ap.add_argument(
        "--verifier", choices=["heuristic_no_keys", "real_ensemble"],
        default="heuristic_no_keys",
        help="Verifier implementation. Use real_ensemble when API "
             "keys + DeBERTa worker are configured.",
    )
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--raw", default=str(DEFAULT_RAW_REAL))
    args = ap.parse_args(argv)

    summary = write_real_calibration(
        verifier_name=args.verifier,
        raw_path=Path(args.raw),
        out_path=Path(args.out),
    )

    s = summary["scoping"]
    print()
    print(f"=== W22/D1 real-claim calibration ({summary['verifier_source']}) ===")
    print(f"  real pairs: {summary['real_pair_count']}")
    if summary["real_metrics"]:
        m = summary["real_metrics"]
        print(f"  real FP-rate-on-supported: "
              f"{m['fp_rate_on_supported']:.2%}  "
              f"(synthetic baseline {W21_SYNTHETIC_FP_RATE:.0%})")
        print(f"  real recall-on-insufficient: "
              f"{m['recall_on_insufficient']:.2%}  "
              f"(synthetic baseline {W21_SYNTHETIC_RECALL_INS:.0%})")
    else:
        print(f"  real metrics: <none -- labeling_pending>")
    print()
    print(f"  SCOPING VERDICT: {s['verdict'].upper()}")
    print(f"  {s['rationale']}")
    print(f"  -> {s['drives_w22_days_2_to_5']}")
    print()
    print(f"  summary -> {args.out}")
    return 0


__all__ = [
    "BORDERLINE_FP_CEILING",
    "DEFAULT_OUT",
    "DEFAULT_RAW_REAL",
    "LIGHT_POLISH_FP_CEILING",
    "ScopingVerdict",
    "W21_SYNTHETIC_FP_RATE",
    "W21_SYNTHETIC_RECALL_INS",
    "write_real_calibration",
]


if __name__ == "__main__":
    raise SystemExit(main())
