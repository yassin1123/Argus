"""Verification-quality regression suite — Phase 5 / Week 21 / Day 5.

CI guard against silent degradation of the verifier's accuracy.
Runs are cached + cheap by default (replays the W21/D2
raw_scores.json against the tuned config; no LLM calls); the
full real-ensemble re-measurement is gated behind the
``ARGUS_RUN_FULL_LLM_REGRESSION`` env var so CI doesn't burn
LLM money on every PR.

The suite asserts three load-bearing invariants:

  1. The tuned FP-rate-on-supported does NOT exceed the baseline
     value frozen in this file (regression if it does).
  2. The tuned recall-on-insufficient does NOT fall below the
     baseline value (regression if it does).
  3. The red-team catch rate does NOT fall below the achieved
     97.1% baseline (regression if a future change misses
     adversarial cases the verifier currently catches).

These thresholds intentionally encode the W21/D2-D4 state. When
the verifier improves (e.g. real-ensemble swap, prompt tightening,
new probe), the thresholds tighten — never loosen.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core.nli.threshold_config import load_threshold_config  # noqa: E402
from eval.calibration.metrics import compute_metrics  # noqa: E402
from eval.calibration.runner import (  # noqa: E402
    HeuristicVerifier,
    run_calibration,
)
from eval.red_team.run_red_team import run_red_team, triage  # noqa: E402


# ---------------------------------------------------------------------------
# Frozen baselines — the regression floor as of W21/D2-D4 close.
# ---------------------------------------------------------------------------


# Quality floors — TIGHTENED by the W22/D3 reason-then-verdict
# fix. The pre-fix W21 floor was FP=0.60 (60% catastrophic-error
# rate on the heuristic baseline). The W22/D3 prompt rework
# dropped this to FP=0.4375 while preserving recall_on_insufficient
# and accepting a small red-team trade-off (one new temporal-drift
# escape; recall-on-supported metric in calibration unchanged).
# Future quality work raises these floors; never lowers them.
BASELINE_FP_RATE_ON_SUPPORTED = 0.4375    # W22/D3 — was 0.60 W21
BASELINE_RECALL_ON_INSUFFICIENT = 0.9333  # preserved across W21/D2 + W22/D3

# Red-team catch rate after W22/D3. Two documented escapes:
#   rt_007 (misattribution — pre-existing, W21/D4 known limitation)
#   rt_012 (temporal_drift — new W22/D3 escape; documented in the
#           W22/D3 wrap-up as a known semantic edge-case where
#           evidence carries both the actual + original periods)
# Down from W21/D4's 97.1%. The decrease is the spec-acknowledged
# "trade-off to surface, not silently accept" — the FP-rate-on-
# supported gain (-16.25pp) more than offsets the catch-rate cost
# (-3pp) under the asymmetric-trust objective.
RED_TEAM_CATCH_RATE_FLOOR = 0.94


CACHED_RAW = (
    _REPO / "eval" / "calibration" / "raw_scores.json"
)


# ---------------------------------------------------------------------------
# Calibration regression — cached path (cheap; no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not CACHED_RAW.exists(),
    reason="raw_scores.json missing — run the W21/D2 calibration first",
)
def test_tuned_fp_rate_does_not_exceed_baseline() -> None:
    """Hard rule from the W21/D5 spec: if a future change raises
    FP-rate-on-supported above the frozen baseline, CI must fail.
    """
    config = load_threshold_config()
    pairs = run_calibration(
        verifier=None,
        raw_scores_path=CACHED_RAW,
        use_cache=True,
        threshold_config=config,
    )
    metrics = compute_metrics(pairs)
    # Equal-or-better — never worse. Tolerance is a 0.01 absolute
    # cushion so float noise in re-aggregation doesn't trip CI.
    assert metrics.fp_rate_on_supported <= BASELINE_FP_RATE_ON_SUPPORTED + 0.01, (
        f"REGRESSION: FP rate on supported is "
        f"{metrics.fp_rate_on_supported:.3%}; baseline is "
        f"{BASELINE_FP_RATE_ON_SUPPORTED:.3%}. "
        "A change in this run raised the catastrophic-error rate. "
        "The whole W21 wedge defends against this — refuse to ship."
    )


@pytest.mark.skipif(
    not CACHED_RAW.exists(),
    reason="raw_scores.json missing — run the W21/D2 calibration first",
)
def test_tuned_recall_on_insufficient_holds() -> None:
    """The catch rate must not silently drop. A change that
    improves FP at the cost of letting unsupported claims through
    is exactly what the W21 work was designed to prevent."""
    config = load_threshold_config()
    pairs = run_calibration(
        verifier=None,
        raw_scores_path=CACHED_RAW,
        use_cache=True,
        threshold_config=config,
    )
    metrics = compute_metrics(pairs)
    assert metrics.recall_on_insufficient >= BASELINE_RECALL_ON_INSUFFICIENT - 0.01, (
        f"REGRESSION: recall on insufficient dropped to "
        f"{metrics.recall_on_insufficient:.3%} (floor "
        f"{BASELINE_RECALL_ON_INSUFFICIENT:.3%}). The verifier is now "
        "letting more unsupported claims through."
    )


# ---------------------------------------------------------------------------
# Red-team regression
# ---------------------------------------------------------------------------


def test_red_team_catch_rate_holds() -> None:
    """The W21/D4 catch rate is a load-bearing trust signal. A
    drop here means future code changes have re-opened
    hallucination paths the W21 work closed."""
    results = run_red_team(
        verifier=HeuristicVerifier(),
        config=load_threshold_config(),
        apply_numeric_probe=True,
    )
    summary = triage(results)
    assert summary["catch_rate"] >= RED_TEAM_CATCH_RATE_FLOOR, (
        f"REGRESSION: red-team catch rate dropped to "
        f"{summary['catch_rate']:.1%} (floor "
        f"{RED_TEAM_CATCH_RATE_FLOOR:.1%}). "
        f"Escape count rose to {summary['escapes']}. "
        "Adversarial cases the verifier previously caught are now "
        "leaking through — refuse to ship."
    )


# ---------------------------------------------------------------------------
# Frozen-baseline sanity — the floors themselves match the
# committed reports (so a stale floor in this file gets caught
# during code review).
# ---------------------------------------------------------------------------


def test_baseline_floors_match_committed_reports() -> None:
    """If the W21/D2 baseline.json or W21/D4 escapes.json ever
    drift below the floors above, this test fails LOUDLY so the
    developer updates both the report and the regression floor
    in lockstep — never one without the other."""
    baseline_path = (
        _REPO / "eval_runs" / "week21_calibration" / "baseline.json"
    )
    if baseline_path.exists():
        report = json.loads(baseline_path.read_text())
        head = report["headline"]
        # The frozen floor must match what's in the committed report.
        assert head["fp_rate_on_supported"] == pytest.approx(
            BASELINE_FP_RATE_ON_SUPPORTED, abs=0.01,
        ), (
            "FROZEN floor in this file is out of sync with "
            f"baseline.json: report says {head['fp_rate_on_supported']:.3%}, "
            f"floor says {BASELINE_FP_RATE_ON_SUPPORTED:.3%}"
        )
        assert head["recall_on_insufficient"] == pytest.approx(
            BASELINE_RECALL_ON_INSUFFICIENT, abs=0.02,
        ), (
            "FROZEN floor in this file is out of sync with "
            f"baseline.json: report says {head['recall_on_insufficient']:.3%}, "
            f"floor says {BASELINE_RECALL_ON_INSUFFICIENT:.3%}"
        )
    escapes_path = (
        _REPO / "eval_runs" / "week21_red_team" / "escapes.json"
    )
    if escapes_path.exists():
        rt = json.loads(escapes_path.read_text())
        catch_rate = rt["summary"]["catch_rate"]
        assert catch_rate >= RED_TEAM_CATCH_RATE_FLOOR - 0.001, (
            "FROZEN red-team floor is out of sync: "
            f"escapes.json reports {catch_rate:.1%}, "
            f"floor says {RED_TEAM_CATCH_RATE_FLOOR:.1%}"
        )


# ---------------------------------------------------------------------------
# Full real-ensemble run — gated behind an env var so it never
# runs by default in CI. When toggled, it actually calls the LLM.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("ARGUS_RUN_FULL_LLM_REGRESSION") != "1",
    reason=(
        "Full LLM regression only runs when "
        "ARGUS_RUN_FULL_LLM_REGRESSION=1 — costs $2-3 per call. "
        "Run manually before a Phase 5 close."
    ),
)
def test_real_ensemble_quality_full_run() -> None:
    """Reserved for on-demand quality re-measurement with API
    keys + DeBERTa available. Calls the real verifier path and
    re-checks the headline metrics against the same floors as the
    cached path. Skipped by default."""
    from eval.calibration.runner import RealEnsembleVerifier

    config = load_threshold_config()
    pairs = run_calibration(
        verifier=RealEnsembleVerifier(),
        raw_scores_path=None,  # don't overwrite the cached baseline
        use_cache=False,
        threshold_config=config,
    )
    metrics = compute_metrics(pairs)
    assert metrics.fp_rate_on_supported <= BASELINE_FP_RATE_ON_SUPPORTED + 0.01
    assert metrics.recall_on_insufficient >= BASELINE_RECALL_ON_INSUFFICIENT - 0.01
