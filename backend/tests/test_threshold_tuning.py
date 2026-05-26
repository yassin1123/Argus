"""Tests for the W21/D3 threshold tuning harness.

Six spec assertions:

  1. tuning reads cached scores — zero LLM calls
  2. objective prioritises FP over FN (asymmetric)
  3. tuned FP-rate-on-supported ≤ baseline FP-rate-on-supported
  4. borderline cases resolve to "partial" (the conservative
     default principle)
  5. tuned thresholds are persisted to the production YAML
  6. over-flagging guardrail is reported in the tuned report
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


from core.nli.aggregator import aggregate  # noqa: E402
from core.nli.deberta_client import NLIResult  # noqa: E402
from core.nli.lexical_overlap import LexicalSignal  # noqa: E402
from core.nli.threshold_config import (  # noqa: E402
    ThresholdConfig,
    default_threshold_config,
    load_threshold_config,
)
from eval.calibration.runner import (  # noqa: E402
    RawScores,
    ScoredPair,
    run_calibration,
)
from eval.calibration.tune import (  # noqa: E402
    assess_over_flagging,
    beats,
    evaluate_config,
    tune,
)


# ---------------------------------------------------------------------------
# Build a small cached-scores file the tuner can read.
# ---------------------------------------------------------------------------


def _make_pair(
    eid: str, *, gt: str, llm: str, deberta_label: str, deberta_conf: float,
    num_score: float = 1.0, category: str = "numeric_claim",
    claim: str = "x", evidence: str = "y", adversarial: bool = False,
) -> dict[str, Any]:
    """Build one cached-scores row in the shape run_calibration's
    cache-replay path expects."""
    raw = RawScores(
        llm_verdict=llm,
        deberta_label=deberta_label,
        deberta_confidence=deberta_conf,
        deberta_softmax=(0.1, 0.7, 0.2)
            if deberta_label == "entailment"
            else (0.7, 0.1, 0.2)
            if deberta_label == "contradiction"
            else (0.2, 0.3, 0.5),
        lexical_numeric_score=num_score,
    )
    return {
        "id": eid,
        "claim": claim,
        "evidence": evidence,
        "category": category,
        "adversarial": adversarial,
        "ground_truth": gt,
        "ensemble_verdict": "weak",            # filled by aggregator
        "ensemble_verdict_collapsed": "partial",
        "reason": "",
        "raw": raw.to_dict(),
        "correct": False,
        "error_kind": None,
    }


def _write_cache(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    payload = {
        "verifier_source": "test_fixture",
        "pair_count": len(rows),
        "scored_pairs": rows,
    }
    p = tmp_path / "raw_scores.json"
    p.write_text(json.dumps(payload, indent=2))
    return p


# A 10-pair fixture designed so the W2/D3 defaults produce 2 FPs
# (predicted supported, actually insufficient) and an aggressive
# tuned config (high deberta_high_conf or non-zero band) collapses
# both to "partial" without losing any insufficient recall.
def _baseline_cache(tmp_path: Path) -> Path:
    rows = [
        # 4 truly supported pairs (high deberta + clean lex)
        _make_pair("s1", gt="supported", llm="supported",
                   deberta_label="entailment", deberta_conf=0.92),
        _make_pair("s2", gt="supported", llm="supported",
                   deberta_label="entailment", deberta_conf=0.90),
        _make_pair("s3", gt="supported", llm="supported",
                   deberta_label="entailment", deberta_conf=0.85),
        _make_pair("s4", gt="supported", llm="supported",
                   deberta_label="entailment", deberta_conf=0.80),
        # 2 FP-traps: LLM said supported + entailment 0.72 + num 1.0
        # → baseline (high=0.7) collapses to supported_high → "supported"
        # but ground truth is insufficient.
        _make_pair("fp1", gt="insufficient", llm="supported",
                   deberta_label="entailment", deberta_conf=0.72,
                   adversarial=True),
        _make_pair("fp2", gt="insufficient", llm="supported",
                   deberta_label="entailment", deberta_conf=0.71,
                   adversarial=True),
        # 2 truly insufficient — LLM unsupported.
        _make_pair("i1", gt="insufficient", llm="unsupported",
                   deberta_label="neutral", deberta_conf=0.40),
        _make_pair("i2", gt="insufficient", llm="unsupported",
                   deberta_label="neutral", deberta_conf=0.35),
        # 2 contradicted.
        _make_pair("c1", gt="contradicted", llm="contradicted",
                   deberta_label="contradiction", deberta_conf=0.75),
        _make_pair("c2", gt="contradicted", llm="contradicted",
                   deberta_label="contradiction", deberta_conf=0.65),
    ]
    return _write_cache(tmp_path, rows)


# ---------------------------------------------------------------------------
# 1. tuning reads cached scores — zero LLM calls
# ---------------------------------------------------------------------------


def test_tuning_reads_cached_scores_no_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The W21/D3 hard rule. Tuning replays from the cache and
    must NEVER call the real LLM. We assert that by patching the
    LLM entry points to blow up if invoked."""
    import core.inference.litellm_client as litellm

    def _explode(*a, **kw):  # noqa: ANN001
        raise AssertionError(
            "tune() called an LLM — that violates W21/D3 hard rule"
        )

    monkeypatch.setattr(litellm, "chat_complete", _explode)

    cache_path = _baseline_cache(tmp_path)
    report = tune(
        raw_scores_path=cache_path,
        out_path=tmp_path / "tuned.json",
        persist_config=False,
    )
    assert report["llm_calls_during_tuning"] == 0
    assert report["tuning_source"] == "cached_raw_scores"
    # The candidate count is the grid size (5 × 5 × 5 = 125).
    assert report["candidates_evaluated"] == 125


# ---------------------------------------------------------------------------
# 2. objective prioritises FP over FN
# ---------------------------------------------------------------------------


def test_objective_prioritizes_fp_over_fn() -> None:
    """A candidate with lower FP-on-supported beats one with lower
    FN, even when the FN-cheaper candidate has better accuracy."""
    baseline = {
        "fp_rate_on_supported": 0.40,
        "recall_on_insufficient": 0.50,
        "per_class": [{"label": "supported", "recall": 0.80}],
        "accuracy": 0.50,
    }
    # Candidate A — strictly less FP than baseline, also slightly
    # better recall-on-insufficient → strictly beats baseline.
    cand_a = {
        "fp_rate_on_supported": 0.10,
        "recall_on_insufficient": 0.60,
        "per_class": [{"label": "supported", "recall": 0.60}],
        "accuracy": 0.55,
    }
    assert beats(cand_a, baseline) is True

    # Candidate B — HIGHER FP than baseline, dramatically higher
    # accuracy + recall-on-supported (i.e. fewer FNs). MUST NOT
    # beat baseline under the asymmetric objective.
    cand_b = {
        "fp_rate_on_supported": 0.60,
        "recall_on_insufficient": 0.90,
        "per_class": [{"label": "supported", "recall": 0.95}],
        "accuracy": 0.90,
    }
    assert beats(cand_b, baseline) is False


# ---------------------------------------------------------------------------
# 3. tuned FP-rate-on-supported ≤ baseline FP
# ---------------------------------------------------------------------------


def test_tuned_reduces_false_positive_rate(tmp_path: Path) -> None:
    cache_path = _baseline_cache(tmp_path)
    report = tune(
        raw_scores_path=cache_path,
        out_path=tmp_path / "tuned.json",
        persist_config=False,
    )
    b = report["baseline_metrics_headline"]["fp_rate_on_supported"]
    t = report["tuned_metrics_headline"]["fp_rate_on_supported"]
    # Baseline has the 2 FPs we planted.
    assert b > 0.0
    # Tuned must NEVER be higher.
    assert t <= b + 1e-9
    # On this fixture the asymmetric objective should drive FP to 0
    # (the band/threshold knobs can collapse the two FP-trap rows
    # to "partial" without losing the legitimate supporteds).
    assert t == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 4. borderline cases resolve to "partial" / "weak", not "supported"
# ---------------------------------------------------------------------------


def test_borderline_resolves_to_safer_verdict() -> None:
    """With a non-zero ``borderline_band``, an LLM-supported claim
    where DeBERTa entailment lands inside ``[high_conf - band,
    high_conf)`` must NOT come back as ``supported_*``."""
    nli_in_band = NLIResult(
        label="entailment", confidence=0.72,
        softmax=(0.05, 0.72, 0.23),
    )
    lex_clean = LexicalSignal(
        numeric_overlap_score=1.0, numeric_missing=[],
        entity_overlap_score=1.0, entity_missing=[],
    )
    # Baseline (band=0): supported_high → "supported"
    base = default_threshold_config()
    verdict, _ = aggregate("supported", nli_in_band, lex_clean, config=base)
    assert verdict in {"supported_high", "supported_low"}
    # Tuned with a 0.1 band — 0.72 lies in [0.6, 0.7) is FALSE
    # (0.72 ≥ 0.7) → still supported. So let's pick a wider band
    # that ACTUALLY covers 0.72:
    tuned = ThresholdConfig(
        deberta_high_conf=0.8, numeric_drift_below=0.95,
        borderline_band=0.1,
    )
    # Now [0.7, 0.8) covers 0.72 → borderline downgrade to "weak".
    verdict_tuned, reason = aggregate(
        "supported", nli_in_band, lex_clean, config=tuned,
    )
    assert verdict_tuned == "weak", (
        f"expected conservative downgrade but got {verdict_tuned!r}; "
        f"reason was {reason!r}"
    )
    # An LLM-supported claim with VERY high DeBERTa confidence
    # (well above the band ceiling) is unaffected — we don't
    # over-downgrade.
    nli_strong = NLIResult(
        label="entailment", confidence=0.95,
        softmax=(0.02, 0.95, 0.03),
    )
    verdict_strong, _ = aggregate(
        "supported", nli_strong, lex_clean, config=tuned,
    )
    assert verdict_strong == "supported_high"


# ---------------------------------------------------------------------------
# 5. tuned thresholds persisted to config
# ---------------------------------------------------------------------------


def test_tuned_thresholds_persisted_to_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``tune(persist_config=True)`` writes the chosen config to
    the project's verification_thresholds.yaml so the next process
    load picks it up."""
    # Redirect the persist target to tmp so we don't clobber the
    # real production config.
    fake_cfg = tmp_path / "verification_thresholds.yaml"
    import core.nli.threshold_config as tc_mod
    monkeypatch.setattr(tc_mod, "_CONFIG_PATH", fake_cfg)

    cache_path = _baseline_cache(tmp_path)
    report = tune(
        raw_scores_path=cache_path,
        out_path=tmp_path / "tuned.json",
        persist_config=True,
    )
    assert report["persisted_config_path"] == str(fake_cfg)
    assert fake_cfg.exists()
    # Round-trip via the loader (replays YAML or JSON depending on
    # whether pyyaml is installed; either way the values match).
    loaded = load_threshold_config(fake_cfg)
    cfg_dict = report["tuned_config"]
    assert loaded.deberta_high_conf == pytest.approx(
        cfg_dict["deberta_high_conf"]
    )
    assert loaded.numeric_drift_below == pytest.approx(
        cfg_dict["numeric_drift_below"]
    )
    assert loaded.borderline_band == pytest.approx(
        cfg_dict["borderline_band"]
    )
    # The persisted config has the right provenance markers.
    assert loaded.source == "w21_d3_tune"
    assert "tuned" in loaded.id.lower() or "tune" in loaded.id.lower()


# ---------------------------------------------------------------------------
# 6. over-flagging guardrail reported
# ---------------------------------------------------------------------------


def test_over_flagging_guardrail_reported(tmp_path: Path) -> None:
    """The tuned report must carry an ``over_flagging`` panel so
    the operator sees the trade-off explicitly. Status escalates
    ok → warn → fail at 30% / 50% of genuinely-supported claims
    diverted to review."""
    # Direct unit test of the assessor first — three regimes.
    ok_m = {"per_class": [{"label": "supported", "recall": 0.95}]}
    warn_m = {"per_class": [{"label": "supported", "recall": 0.65}]}  # 35% flagged
    fail_m = {"per_class": [{"label": "supported", "recall": 0.40}]}  # 60% flagged

    assert assess_over_flagging(ok_m)["status"] == "ok"
    assert assess_over_flagging(warn_m)["status"] == "warn"
    assert assess_over_flagging(fail_m)["status"] == "fail"
    assert assess_over_flagging(warn_m)["supported_review_fraction"] == (
        pytest.approx(0.35)
    )

    # End-to-end: a real tuned report carries the panel.
    cache_path = _baseline_cache(tmp_path)
    report = tune(
        raw_scores_path=cache_path,
        out_path=tmp_path / "tuned.json",
        persist_config=False,
    )
    assert "over_flagging" in report
    panel = report["over_flagging"]
    assert panel["status"] in {"ok", "warn", "fail"}
    assert "supported_review_fraction" in panel
    assert isinstance(panel["message"], str) and panel["message"]
    # On the synthetic 10-pair fixture above (4 strong supporteds,
    # all with deberta > 0.8) the tuned config should NOT push
    # supported claims into review — so panel status is "ok".
    assert panel["status"] == "ok"
