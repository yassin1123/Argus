"""Aggregator truth-table tests (Phase 1 / Week 2 / Day 3).

One parametrized case per row of the truth table in
``backend/core/nli/aggregator.py``. The numbers are LOCKED for Day 3
per the spec — if a row reads weird in production data, Day 4's
regression run is where we'd push back, not here.
"""

from __future__ import annotations

import pytest

from core.nli.aggregator import aggregate
from core.nli.deberta_client import NLIResult
from core.nli.lexical_overlap import LexicalSignal


# ---------------------------------------------------------------------------
# Helpers — building the inputs concisely
# ---------------------------------------------------------------------------


def _nli(label: str, conf: float) -> NLIResult:
    """Build an NLIResult with a synthetic softmax that puts ``conf`` on
    ``label``. The aggregator only reads label + confidence; the softmax
    is informational, so we just put 1-conf on contradiction (or whatever
    isn't the argmax) without caring about exact distribution.
    """
    rest = (1.0 - conf) / 2.0
    if label == "contradiction":
        sm = (conf, rest, rest)
    elif label == "entailment":
        sm = (rest, conf, rest)
    elif label == "neutral":
        sm = (rest, rest, conf)
    else:
        # Unknown sentinel (e.g. worker-timeout fallback).
        sm = (1 / 3, 1 / 3, 1 / 3)
    return NLIResult(label=label, confidence=conf, softmax=sm)  # type: ignore[arg-type]


def _lex(score: float, missing: list[str] | None = None) -> LexicalSignal:
    return LexicalSignal(
        numeric_overlap_score=score,
        numeric_missing=list(missing or []),
        entity_overlap_score=1.0,
        entity_missing=[],
    )


# ---------------------------------------------------------------------------
# Truth table rows — exact spec from backend/core/nli/aggregator.py
# ---------------------------------------------------------------------------


def test_row_supported_entailment_high_conf_no_drift() -> None:
    verdict, reason = aggregate("supported", _nli("entailment", 0.85), _lex(1.0))
    assert verdict == "supported_high"
    assert reason == "all signals agree"


def test_row_supported_entailment_high_conf_with_drift() -> None:
    verdict, reason = aggregate(
        "supported",
        _nli("entailment", 0.92),
        _lex(0.5, missing=["50%"]),
    )
    assert verdict == "supported_low"
    assert "numeric drift" in reason
    assert "50%" in reason


def test_row_supported_entailment_low_conf_no_drift() -> None:
    verdict, reason = aggregate("supported", _nli("entailment", 0.55), _lex(1.0))
    assert verdict == "supported_low"
    assert "low-confidence" in reason
    assert "0.55" in reason


def test_row_supported_entailment_low_conf_with_drift() -> None:
    verdict, reason = aggregate(
        "supported",
        _nli("entailment", 0.55),
        _lex(0.5, missing=["50%"]),
    )
    assert verdict == "weak"
    assert reason == "DeBERTa weak entailment + numeric drift"


def test_row_supported_neutral_no_drift() -> None:
    verdict, reason = aggregate("supported", _nli("neutral", 0.80), _lex(1.0))
    assert verdict == "weak"
    assert "anchored on gist" in reason


def test_row_supported_neutral_with_drift() -> None:
    verdict, reason = aggregate(
        "supported",
        _nli("neutral", 0.80),
        _lex(0.4, missing=["€2.4B", "30%"]),
    )
    assert verdict == "weak"
    assert "neutral" in reason
    assert "numeric drift" in reason
    assert "€2.4B" in reason  # first missing surfaces


def test_row_supported_contradiction_any_conf_with_missing() -> None:
    verdict, reason = aggregate(
        "supported",
        _nli("contradiction", 0.90),
        _lex(0.0, missing=["1,500"]),
    )
    assert verdict == "contradicted"
    assert "0.90" in reason
    assert "1,500" in reason


def test_row_supported_contradiction_low_conf_no_missing() -> None:
    """DeBERTa contradiction with low confidence still wins as
    contradicted — confidence threshold is 'any' for contradictions.
    """
    verdict, reason = aggregate("supported", _nli("contradiction", 0.40), _lex(1.0))
    assert verdict == "contradicted"
    assert "0.40" in reason
    assert "see chunk" in reason  # no first_missing to surface


def test_row_llm_weak_sticky() -> None:
    """Sticky: even with high-conf entailment + perfect overlap, LLM weak stays weak."""
    verdict, reason = aggregate("weak", _nli("entailment", 0.99), _lex(1.0))
    assert verdict == "weak"
    assert reason == "LLM weak (sticky)"


def test_row_llm_unsupported_sticky() -> None:
    verdict, reason = aggregate("unsupported", _nli("entailment", 0.99), _lex(1.0))
    assert verdict == "unsupported"
    assert reason == "LLM unsupported (sticky)"


def test_row_llm_overstates_collapses_to_weak() -> None:
    verdict, reason = aggregate("overstates", _nli("entailment", 0.99), _lex(1.0))
    assert verdict == "weak"
    assert "overstates" in reason


def test_row_llm_contradicted_sticky() -> None:
    verdict, reason = aggregate("contradicted", _nli("entailment", 0.99), _lex(1.0))
    assert verdict == "contradicted"
    assert reason == "LLM contradicted (sticky)"


# ---------------------------------------------------------------------------
# Edge cases — never-upgrades invariant + worker-timeout sentinel
# ---------------------------------------------------------------------------


def test_aggregator_never_upgrades_llm_verdict() -> None:
    """Pairwise: every LLM verdict OTHER than supported should not be
    upgraded to a stronger verdict by any DeBERTa + lexical combo.
    """
    perfect_signals = (_nli("entailment", 0.99), _lex(1.0))
    for llm in ("weak", "unsupported", "overstates", "contradicted"):
        v, _ = aggregate(llm, *perfect_signals)
        # The aggregator's output for non-"supported" LLM verdicts is one of
        # weak / unsupported / contradicted — never any "supported_*".
        assert not v.startswith("supported"), (
            f"aggregator upgraded llm_verdict={llm!r} to {v!r} — "
            "this violates the never-upgrade invariant."
        )


def test_unknown_deberta_label_treated_as_neutral_like() -> None:
    """When the DeBERTa worker times out we substitute label='unknown',
    confidence=0. Aggregator should not crash and should produce a
    weak-class verdict (not supported_*).
    """
    timeout_sentinel = NLIResult(label="unknown", confidence=0.0, softmax=(0.0, 0.0, 0.0))  # type: ignore[arg-type]
    verdict, reason = aggregate("supported", timeout_sentinel, _lex(1.0))
    assert verdict == "weak"
    assert "unrecognised" in reason


def test_unknown_llm_verdict_is_weak() -> None:
    """Defensive: any non-recognised LLM verdict string becomes weak."""
    verdict, reason = aggregate("partial", _nli("entailment", 0.99), _lex(1.0))
    assert verdict == "weak"
    assert "not recognised" in reason


def test_zero_numerics_in_claim_is_treated_as_no_drift() -> None:
    """If the claim has no numerics, the lexical scorer returns score=1.0
    and empty missing — the aggregator should treat that as the no-drift
    branch, not as a missed signal.
    """
    no_numerics = LexicalSignal(
        numeric_overlap_score=1.0,
        numeric_missing=[],
        entity_overlap_score=1.0,
        entity_missing=[],
    )
    verdict, reason = aggregate("supported", _nli("entailment", 0.95), no_numerics)
    assert verdict == "supported_high"
    assert reason == "all signals agree"


# ---------------------------------------------------------------------------
# Threshold boundaries — exact-equality lands on the high-confidence side
# ---------------------------------------------------------------------------


def test_deberta_conf_exactly_threshold_is_high() -> None:
    """Boundary: confidence == 0.7 should count as high-confidence (>=)."""
    verdict, _ = aggregate("supported", _nli("entailment", 0.70), _lex(1.0))
    assert verdict == "supported_high"


def test_numeric_score_exactly_threshold_is_no_drift() -> None:
    """Boundary: score == 0.95 should count as no-drift (>=)."""
    verdict, _ = aggregate("supported", _nli("entailment", 0.95), _lex(0.95))
    assert verdict == "supported_high"
