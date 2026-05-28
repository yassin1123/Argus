"""W24/D1 real-claim calibration gate tests.

Phase 5 / Week 24 / Day 1. These are the gate's acceptance
criteria expressed as tests:

  - ≥40 real claims are labelled,
  - the calibration ran through the real cross-family verifier,
  - the pilot verdict applies the GREEN/YELLOW/RED thresholds,
  - the recall-on-insufficient safety floor is enforced,
  - the regression baseline carries the real-claim numbers.

The threshold-logic tests are pure functions (no I/O, no LLM) and
always run. The artifact tests read the committed
``week24_real_calibration/`` outputs — they're the "Day 1 is
actually done" checks and pass once the labelled batch + real
calibration run land.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from eval.calibration.run_calibration import (  # noqa: E402
    GREEN_FP_CEILING,
    MIN_LABELLED_PAIRS,
    RECALL_ON_INSUFFICIENT_FLOOR,
    YELLOW_FP_CEILING,
    classify_pilot_verdict,
)
from eval.golden_set.loader import load_real_run_entries  # noqa: E402

_SUMMARY = (
    _BACKEND / "eval_runs" / "week24_real_calibration" / "summary.json"
)
_VERDICT = (
    _BACKEND / "eval_runs" / "week24_real_calibration" / "pilot_verdict.json"
)


def _real_entries():
    return [e for e in load_real_run_entries() if e.evidence_source == "real_run"]


# ---------------------------------------------------------------------------
# 1. ≥40 labelled real pairs
# ---------------------------------------------------------------------------


def test_min_40_real_labels_loaded() -> None:
    """The gate floor: below 40 labelled pairs the statistical
    signal is too weak for a pilot decision."""
    entries = _real_entries()
    assert len(entries) >= MIN_LABELLED_PAIRS, (
        f"Only {len(entries)} labelled real-claim pairs; the gate "
        f"requires ≥{MIN_LABELLED_PAIRS}. Run tools/label_claims.py "
        "against backend/eval/golden_set/real_runs/_worksheet_w24d1.json."
    )
    # Every entry must carry a real ground-truth verdict + non-empty
    # evidence (the labellable surface).
    valid = {"supported", "partial", "insufficient", "contradicted"}
    for e in entries:
        assert e.ground_truth in valid, f"{e.id}: bad label {e.ground_truth!r}"
        assert (e.evidence or "").strip(), f"{e.id}: empty evidence"


# ---------------------------------------------------------------------------
# 2. Calibration ran through the real cross-family verifier
# ---------------------------------------------------------------------------


def test_calibration_runs_through_real_verifier() -> None:
    """verifier_source must be cross_family_llm — never the
    heuristic substitute (the W22 bug class). The fail-loud config
    + the gate-check make a degraded run impossible to mislabel."""
    assert _SUMMARY.exists(), (
        "week24_real_calibration/summary.json missing — run "
        "backend/eval/calibration/run_calibration.py --set real "
        "--verifier cross_family_llm."
    )
    summary = json.loads(_SUMMARY.read_text(encoding="utf-8"))
    assert summary["gate_status"] == "complete", (
        f"gate_status={summary['gate_status']!r}; expected 'complete'."
    )
    assert summary["verifier_source"] == "cross_family_llm", (
        f"verifier_source={summary['verifier_source']!r}; the gate must "
        "run the full cross-family ensemble, not a degraded fallback."
    )
    assert summary["real_pair_count"] >= MIN_LABELLED_PAIRS
    assert summary["real_metrics"] is not None


# ---------------------------------------------------------------------------
# 3. Pilot verdict applies the thresholds (pure function)
# ---------------------------------------------------------------------------


def test_pilot_verdict_applies_thresholds() -> None:
    """GREEN ≤5%, YELLOW 5-15%, RED >15% — boundaries asserted
    directly against the classifier."""
    good_recall = 0.95

    green = classify_pilot_verdict(
        fp_rate=0.03, recall_on_insufficient=good_recall,
        pair_count=45, verifier_source="cross_family_llm",
    )
    assert green.band == "GREEN"
    assert green.proceeds is True
    assert green.posture == "verified"

    # Exactly on the GREEN ceiling is still GREEN.
    on_green = classify_pilot_verdict(
        fp_rate=GREEN_FP_CEILING, recall_on_insufficient=good_recall,
        pair_count=45, verifier_source="cross_family_llm",
    )
    assert on_green.band == "GREEN"

    yellow = classify_pilot_verdict(
        fp_rate=0.10, recall_on_insufficient=good_recall,
        pair_count=45, verifier_source="cross_family_llm",
    )
    assert yellow.band == "YELLOW"
    assert yellow.proceeds is True
    assert yellow.posture == "ai_assisted_human_review"

    # Exactly on the YELLOW ceiling is still YELLOW (a pass).
    on_yellow = classify_pilot_verdict(
        fp_rate=YELLOW_FP_CEILING, recall_on_insufficient=good_recall,
        pair_count=45, verifier_source="cross_family_llm",
    )
    assert on_yellow.band == "YELLOW"
    assert on_yellow.proceeds is True

    red = classify_pilot_verdict(
        fp_rate=0.20, recall_on_insufficient=good_recall,
        pair_count=45, verifier_source="cross_family_llm",
    )
    assert red.band == "RED"
    assert red.proceeds is False
    assert "verifier_work" in red.posture


# ---------------------------------------------------------------------------
# 4. Recall-on-insufficient safety floor
# ---------------------------------------------------------------------------


def test_recall_on_insufficient_safety_check() -> None:
    """A green FP rate with a broken catch rate is NOT a clean
    pilot. Recall below the floor downgrades the posture even when
    FP is green."""
    breached = classify_pilot_verdict(
        fp_rate=0.02,  # would be GREEN on FP alone
        recall_on_insufficient=0.70,  # below the 0.85 floor
        pair_count=45, verifier_source="cross_family_llm",
    )
    assert breached.recall_safety_ok is False
    assert breached.proceeds is False
    assert breached.posture == "pilot_blocked_safety_floor_breached"

    # Exactly on the floor is OK.
    on_floor = classify_pilot_verdict(
        fp_rate=0.02,
        recall_on_insufficient=RECALL_ON_INSUFFICIENT_FLOOR,
        pair_count=45, verifier_source="cross_family_llm",
    )
    assert on_floor.recall_safety_ok is True
    assert on_floor.proceeds is True


# ---------------------------------------------------------------------------
# 5. Regression baseline carries the real-claim numbers
# ---------------------------------------------------------------------------


def test_regression_baseline_updated_to_real_numbers() -> None:
    """The production-relevant truth — the real-claim FP rate +
    recall — must be frozen in the regression baseline so a future
    change that degrades real-claim quality trips CI."""
    from tests import test_verification_quality_regression as reg

    assert hasattr(reg, "REAL_CLAIM_FP_RATE_ON_SUPPORTED"), (
        "regression baseline missing REAL_CLAIM_FP_RATE_ON_SUPPORTED — "
        "update test_verification_quality_regression.py with the W24/D1 "
        "real-claim numbers."
    )
    assert hasattr(reg, "REAL_CLAIM_RECALL_ON_INSUFFICIENT")
    assert hasattr(reg, "REAL_CLAIM_PAIR_COUNT")

    # The frozen baseline must agree with the committed verdict.
    assert _VERDICT.exists(), "pilot_verdict.json missing."
    verdict = json.loads(_VERDICT.read_text(encoding="utf-8"))
    assert reg.REAL_CLAIM_FP_RATE_ON_SUPPORTED == pytest.approx(
        verdict["real_fp_rate_on_supported"], abs=0.001,
    ), "baseline FP rate disagrees with the committed pilot verdict."
    assert reg.REAL_CLAIM_RECALL_ON_INSUFFICIENT == pytest.approx(
        verdict["real_recall_on_insufficient"], abs=0.001,
    )
    assert reg.REAL_CLAIM_PAIR_COUNT == verdict["real_pair_count"]
    # The safety floor must hold in the frozen numbers.
    assert (
        reg.REAL_CLAIM_RECALL_ON_INSUFFICIENT
        >= RECALL_ON_INSUFFICIENT_FLOOR
    ), "frozen real-claim recall is below the safety floor."
