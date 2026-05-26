"""Tests for the W22/D4 re-calibration + before/after.

Five spec assertions:

  1. re-calibration on post-fix scores produces the full metrics
     (confusion matrix, FP, recall, per-category)
  2. re-tuning the threshold harness against the new cached
     scores triggers zero LLM calls
  3. the over-flagging guardrail is rechecked + transitions from
     W21 fail toward a usable state
  4. the red-team rerun catch rate is recorded with per-exploit
     breakdown
  5. the before/after comparison + pilot-readiness verdict are
     complete and honest
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from eval.calibration.recalibrate import (  # noqa: E402
    HUMAN_REVIEW_FP_CEILING,
    HUMAN_REVIEW_RED_TEAM_FLOOR,
    READY_FP_CEILING,
    READY_RED_TEAM_FLOOR,
    W21_BASELINE,
    build_comparison,
    classify_pilot_readiness,
    recalibrate,
)


# ---------------------------------------------------------------------------
# 1. re-calibration produces the full metrics
# ---------------------------------------------------------------------------


def test_recalibration_post_fix() -> None:
    """The post_fix.json shape carries the full metrics block +
    the over-flag panel + failure cases, all from the cached
    raw_scores.json (zero LLM)."""
    raw = _REPO / "eval" / "calibration" / "raw_scores.json"
    if not raw.exists():
        pytest.skip("raw_scores.json missing; run the W21/D2 calibration")
    report = recalibrate(raw)
    h = report["headline"]
    m = report["metrics"]
    assert "fp_rate_on_supported" in h
    assert "recall_on_insufficient" in h
    assert "confusion" in m
    assert set(m["confusion"].keys()) == {
        "supported", "partial", "insufficient", "contradicted",
    }
    assert "per_category_accuracy" in m
    assert set(m["per_category_accuracy"].keys()) == {
        "numeric_claim", "causal_claim", "comparative",
        "attribution", "forecast",
    }
    # The over-flag panel is part of the report.
    assert "over_flagging" in report
    assert report["over_flagging"]["status"] in {"ok", "warn", "fail"}


# ---------------------------------------------------------------------------
# 2. re-tuning uses cached scores only (zero LLM)
# ---------------------------------------------------------------------------


def test_retune_against_new_scores_no_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per the W22/D4 hard rule: re-tuning runs against the cache
    and never touches the LLM. We assert that by patching the
    LLM call to blow up if invoked, then running the tuner."""
    raw = _REPO / "eval" / "calibration" / "raw_scores.json"
    if not raw.exists():
        pytest.skip("raw_scores.json missing")

    import core.inference.litellm_client as litellm
    monkeypatch.setattr(
        litellm, "chat_complete",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("LLM called during re-tuning -- W22/D4 hard rule")
        ),
    )

    from eval.calibration.tune import tune

    # Use a tmp out path so we don't overwrite the committed
    # tuned.json under the test.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "tuned.json"
        report = tune(
            raw_scores_path=raw,
            out_path=out,
            persist_config=False,
        )
    assert report["llm_calls_during_tuning"] == 0
    assert report["tuning_source"] == "cached_raw_scores"
    # Whatever the tuner picks, the chosen FP-rate must NEVER
    # exceed the committed baseline.
    assert (
        report["tuned_metrics_headline"]["fp_rate_on_supported"]
        <= report["baseline_metrics_headline"]["fp_rate_on_supported"]
        + 1e-9
    )


# ---------------------------------------------------------------------------
# 3. over-flagging guardrail re-checked
# ---------------------------------------------------------------------------


def test_overflagging_rechecked() -> None:
    """The W21 over-flag fraction was 86.7% (FAIL). After the
    W22/D3 fix the same guardrail must NOT be worse, and ideally
    transitions toward 'warn' or 'ok'."""
    raw = _REPO / "eval" / "calibration" / "raw_scores.json"
    if not raw.exists():
        pytest.skip("raw_scores.json missing")
    report = recalibrate(raw)
    of = report["over_flagging"]
    w21_fraction = W21_BASELINE["supported_review_fraction"]
    # Must not have gotten worse.
    assert of["supported_review_fraction"] <= w21_fraction + 0.01, (
        f"over-flag fraction regressed: was {w21_fraction:.2%}, "
        f"now {of['supported_review_fraction']:.2%}"
    )
    # Must be in a known status.
    assert of["status"] in {"ok", "warn", "fail"}
    # FAIL→WARN/OK transition is the W22/D4 success signal.
    if W21_BASELINE["over_flag_status"] == "fail":
        assert of["status"] in {"ok", "warn"}, (
            "W22/D3 fix should at least move over-flag out of FAIL"
        )


# ---------------------------------------------------------------------------
# 4. red-team rerun catch rate
# ---------------------------------------------------------------------------


def test_red_team_rerun_catch_rate() -> None:
    """The committed W21 escapes.json was regenerated by the
    W22/D3 fix-run. The comparison surfaces:
      - the post-fix catch rate
      - per-exploit-type breakdown
      - escape ids the operator must triage
    """
    raw = _REPO / "eval" / "calibration" / "raw_scores.json"
    if not raw.exists():
        pytest.skip("raw_scores.json missing")
    post = recalibrate(raw)
    comp = build_comparison(post)
    pf = comp["w22_post_fix"]
    assert "red_team_catch_rate" in pf
    assert "red_team_escapes" in pf
    assert "red_team_escape_ids" in pf
    # The W21 baseline catch rate is frozen in W21_BASELINE; the
    # post-fix must be within 5pp (acceptable trade-off ceiling per
    # the W22/D3 wrap-up).
    if pf["red_team_catch_rate"] is not None:
        delta_pp = (
            pf["red_team_catch_rate"]
            - W21_BASELINE["red_team_catch_rate"]
        ) * 100
        assert delta_pp >= -5.0, (
            f"red-team catch rate dropped {-delta_pp:.1f}pp; "
            "exceeds the 5pp acceptable trade-off ceiling. "
            "Refuse to ship until the heuristic recovers."
        )
    # Per-exploit breakdown present.
    assert "red_team_per_exploit" in comp
    rt_per = comp["red_team_per_exploit"]
    # Every exploit category from the W21/D4 set must have an entry.
    for exploit in (
        "magnitude_mismatch", "misattribution", "temporal_drift",
        "overclaim", "fabricated_specific", "plausible_but_absent",
        "negation_flip", "cherry_pick",
    ):
        assert exploit in rt_per, f"missing exploit type {exploit!r}"
        bucket = rt_per[exploit]
        assert "catch_rate" in bucket
        assert "caught" in bucket
        assert "total" in bucket


# ---------------------------------------------------------------------------
# 5. before/after comparison + pilot-readiness verdict
# ---------------------------------------------------------------------------


def test_before_after_comparison_complete() -> None:
    """The comparison artifact carries: W21 baseline, W22 post-fix,
    delta panel (every metric), red-team breakdown, and the
    pilot-readiness verdict (one of ready / human_review_required /
    not_ready)."""
    raw = _REPO / "eval" / "calibration" / "raw_scores.json"
    if not raw.exists():
        pytest.skip("raw_scores.json missing")
    post = recalibrate(raw)
    comp = build_comparison(post)
    # Required top-level sections.
    for key in (
        "w21_baseline", "w22_post_fix", "deltas",
        "red_team_per_exploit", "pilot_readiness",
    ):
        assert key in comp, f"missing section {key!r}"
    # Deltas must include every load-bearing metric.
    d = comp["deltas"]
    for k in (
        "fp_rate_on_supported_pp",
        "recall_on_insufficient_pp",
        "accuracy_pp",
        "supported_review_fraction_pp",
        "red_team_catch_rate_pp",
    ):
        assert k in d
    # FP delta must be improvement (negative pp) or zero.
    assert d["fp_rate_on_supported_pp"] <= 0.0, (
        f"FP regressed: delta {d['fp_rate_on_supported_pp']:+.2f}pp"
    )
    # Recall delta must not be negative beyond noise.
    assert d["recall_on_insufficient_pp"] >= -1.0
    # Pilot verdict must be one of the three honest outcomes.
    v = comp["pilot_readiness"]
    assert v["verdict"] in {
        "ready", "human_review_required", "not_ready",
    }
    assert v["headline"]
    assert v["rationale"]
    assert isinstance(v["next_steps"], list) and v["next_steps"]


# ---------------------------------------------------------------------------
# Pilot-readiness verdict classifier — direct unit test
# ---------------------------------------------------------------------------


def test_pilot_readiness_classifier_three_outcomes() -> None:
    """The classifier maps the three FP/over-flag/red-team
    combinations onto the three honest outcomes."""
    # ready
    v = classify_pilot_readiness(
        fp_rate_post_fix=0.05,
        over_flag_status="ok",
        red_team_catch_rate=0.97,
    )
    assert v.verdict == "ready"

    # human_review_required
    v = classify_pilot_readiness(
        fp_rate_post_fix=0.4375,   # the actual W22 post-fix value
        over_flag_status="warn",
        red_team_catch_rate=0.9412,
    )
    assert v.verdict == "human_review_required"

    # not_ready — FP too high
    v = classify_pilot_readiness(
        fp_rate_post_fix=0.70,
        over_flag_status="warn",
        red_team_catch_rate=0.94,
    )
    assert v.verdict == "not_ready"

    # not_ready — over-flag still fail
    v = classify_pilot_readiness(
        fp_rate_post_fix=0.30,
        over_flag_status="fail",
        red_team_catch_rate=0.94,
    )
    assert v.verdict == "not_ready"
