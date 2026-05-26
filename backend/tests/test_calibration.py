"""Tests for the W21/D2 calibration measurement.

Seven spec assertions:

  1. calibration runs against the golden set (every pair scored)
  2. raw scores are cached to a JSON file Day 3 can replay
  3. confusion matrix is computed (4×4, dense)
  4. FP rate on supported is the catastrophic-error metric we expect
  5. recall on insufficient is the catch rate we expect
  6. per-category breakdown is produced
  7. failure cases split cleanly into FP vs FN vs other

The runner is exercised with a controlled-stub verifier so the
test is deterministic + cheap. The real heuristic + real-ensemble
verifiers are exercised by the manual baseline run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from eval.calibration.metrics import (  # noqa: E402
    CalibrationMetrics,
    compute_metrics,
    confusion_matrix,
    split_failures,
)
from eval.calibration.runner import (  # noqa: E402
    HeuristicVerifier,
    RawScores,
    VerifierProtocol,
    load_scored_pairs,
    run_calibration,
)
from eval.golden_set import GoldenEntry, GoldenSet  # noqa: E402


# ---------------------------------------------------------------------------
# Test fixtures: a controlled-stub verifier + a tiny synthetic golden set
# ---------------------------------------------------------------------------


def _entry(
    eid: str, claim: str, evidence: str, gt: str, cat: str,
    adversarial: bool = False,
) -> GoldenEntry:
    return GoldenEntry(
        id=eid, claim=claim, evidence=evidence,
        evidence_source="synthetic",
        ground_truth=gt, label_rationale="test",
        category=cat, adversarial=adversarial,
    )


def _golden() -> GoldenSet:
    """Six-pair tiny golden set, hand-picked so the metrics have
    known answers. Every claim string is unique so the _TableVerifier
    can map claim → id unambiguously."""
    return GoldenSet(entries=[
        # Two correct supported
        _entry("t1", "Revenue grew 12% YoY.",
               "Revenue grew 12% year over year.", "supported", "numeric_claim"),
        _entry("t2", "Operating margin expanded materially.",
               "EBITDA margin expanded 220 bps.", "supported", "numeric_claim"),
        # One FALSE POSITIVE: verifier says supported, truth is insufficient
        _entry("t3", "Revenue grew 14% in FY2023.",
               "FY2023 results were presented.", "insufficient", "numeric_claim",
               adversarial=True),
        # One FALSE NEGATIVE: verifier says weak/insufficient, truth is supported
        _entry("t4", "Capex was £15m in FY2023.",
               "Total capex in FY2023 amounted to £15m.", "supported",
               "numeric_claim"),
        # One correct contradicted
        _entry("t5", "Revenue grew in the period.",
               "Revenue declined 8%.", "contradicted", "numeric_claim"),
        # One correct insufficient
        _entry("t6", "Gross margin expanded YoY.",
               "The CFO discussed working capital priorities.",
               "insufficient", "causal_claim"),
    ])


class _StubVerifier:
    """Verdicts hard-coded per id so the metrics have a known truth.
    Lets us validate every metric end-to-end without an LLM."""

    name = "test_stub"

    def score(self, claim: str, evidence: str) -> RawScores:
        # Encode the verdict in the claim string we'll see (the
        # test passes claims with known ids embedded in them).
        # Real test calls use the lookup table below.
        return RawScores(llm_verdict="weak")


_STUB_TABLE: dict[str, tuple[str, str, float]] = {
    # id -> (llm_verdict, deberta_label, deberta_conf, lex_num)
    "t1": ("supported", "entailment", 0.85),
    "t2": ("supported", "entailment", 0.80),
    "t3": ("supported", "entailment", 0.85),   # FP — agrees with FP-inducing case
    "t4": ("weak",      "neutral",    0.50),   # FN
    "t5": ("contradicted", "contradiction", 0.78),
    "t6": ("unsupported", "neutral",  0.40),
}


class _TableVerifier:
    """Looks up RawScores by claim-text suffix (we wire the id into
    the claim in the test). Used so every metric calc has a
    deterministic input."""

    name = "test_table"

    def __init__(self, by_id: dict[str, tuple[str, str, float]]) -> None:
        self.by_id = by_id
        self._claim_to_id: dict[str, str] = {}

    def register(self, claim: str, eid: str) -> None:
        self._claim_to_id[claim] = eid

    def score(self, claim: str, evidence: str) -> RawScores:
        eid = self._claim_to_id.get(claim, "t1")
        llm_v, d_label, d_conf = self.by_id[eid]
        # Make supported predictions land cleanly: numeric_score 1.0
        # + entailment + conf >= 0.7 → ensemble = supported_high.
        # FN id (t4): neutral + lex 1.0 → ensemble = weak.
        return RawScores(
            llm_verdict=llm_v,
            deberta_label=d_label,
            deberta_confidence=d_conf,
            deberta_softmax=(0.1, 0.7, 0.2),
            lexical_numeric_score=1.0,
            lexical_entity_score=1.0,
        )


def _wire_verifier(gs: GoldenSet) -> _TableVerifier:
    v = _TableVerifier(_STUB_TABLE)
    for e in gs:
        v.register(e.claim, e.id)
    return v


# ---------------------------------------------------------------------------
# 1. calibration runs against the golden set
# ---------------------------------------------------------------------------


def test_calibration_runs_against_golden_set(tmp_path: Path) -> None:
    gs = _golden()
    verifier = _wire_verifier(gs)
    pairs = run_calibration(
        verifier=verifier, golden_set=gs,
        raw_scores_path=tmp_path / "raw.json",
    )
    assert len(pairs) == 6
    assert {p.id for p in pairs} == {"t1", "t2", "t3", "t4", "t5", "t6"}
    # Every pair has a verdict + a collapsed verdict + a correctness flag.
    for p in pairs:
        assert p.ensemble_verdict
        assert p.ensemble_verdict_collapsed in {
            "supported", "partial", "insufficient", "contradicted",
        }
        assert isinstance(p.correct, bool)


# ---------------------------------------------------------------------------
# 2. raw scores cached
# ---------------------------------------------------------------------------


def test_raw_scores_cached(tmp_path: Path) -> None:
    """raw_scores.json must round-trip back into ScoredPair objects
    so Day 3 can replay without re-LLM."""
    gs = _golden()
    verifier = _wire_verifier(gs)
    raw_path = tmp_path / "raw.json"
    pairs = run_calibration(
        verifier=verifier, golden_set=gs, raw_scores_path=raw_path,
    )
    assert raw_path.exists()
    payload = json.loads(raw_path.read_text())
    assert payload["pair_count"] == 6
    assert payload["verifier_source"] == "test_table"
    assert len(payload["scored_pairs"]) == 6

    # Replay-from-cache must produce the same ensemble verdicts.
    cached_pairs = run_calibration(
        verifier=None, golden_set=gs, raw_scores_path=raw_path,
        use_cache=True,
    )
    for original, replay in zip(pairs, cached_pairs):
        assert original.id == replay.id
        assert original.ensemble_verdict == replay.ensemble_verdict
        assert original.raw.llm_verdict == replay.raw.llm_verdict

    # And load_scored_pairs round-trips too.
    loaded = load_scored_pairs(raw_path)
    assert [p.id for p in loaded] == [p.id for p in pairs]


# ---------------------------------------------------------------------------
# 3. confusion matrix
# ---------------------------------------------------------------------------


def test_confusion_matrix_computed(tmp_path: Path) -> None:
    gs = _golden()
    pairs = run_calibration(
        verifier=_wire_verifier(gs), golden_set=gs,
        raw_scores_path=tmp_path / "raw.json",
    )
    cm = confusion_matrix(pairs)
    # 4×4, dense (every cell exists, even zero).
    assert set(cm.keys()) == {"supported", "partial", "insufficient", "contradicted"}
    for predicted_row in cm.values():
        assert set(predicted_row.keys()) == {
            "supported", "partial", "insufficient", "contradicted",
        }
    # The supported→supported cell should be 2 (t1, t2).
    assert cm["supported"]["supported"] == 2
    # The supported→insufficient cell should be 1 (t3 FP).
    assert cm["supported"]["insufficient"] == 1
    # The contradicted→contradicted cell should be 1 (t5).
    assert cm["contradicted"]["contradicted"] == 1


# ---------------------------------------------------------------------------
# 4. FP rate on supported (catastrophic-error metric)
# ---------------------------------------------------------------------------


def test_false_positive_rate_on_supported(tmp_path: Path) -> None:
    """Of every claim the verifier called supported, what fraction
    was actually NOT supported? In this set the verifier predicts
    supported 3× (t1, t2, t3); only t3 is wrong → 1/3."""
    gs = _golden()
    pairs = run_calibration(
        verifier=_wire_verifier(gs), golden_set=gs,
        raw_scores_path=tmp_path / "raw.json",
    )
    m = compute_metrics(pairs)
    assert m.supported_predictions == 3
    assert m.fp_count_on_supported == 1
    assert m.fp_rate_on_supported == pytest.approx(1 / 3)


# ---------------------------------------------------------------------------
# 5. recall on insufficient (catch rate)
# ---------------------------------------------------------------------------


def test_recall_on_unsupported(tmp_path: Path) -> None:
    """Of every claim that's actually insufficient, what fraction
    did the verifier NOT call supported? Set has t3 + t6 as
    ground-truth insufficient. The verifier calls t3 supported
    (missed) and t6 unsupported (caught) → recall 1/2."""
    gs = _golden()
    pairs = run_calibration(
        verifier=_wire_verifier(gs), golden_set=gs,
        raw_scores_path=tmp_path / "raw.json",
    )
    m = compute_metrics(pairs)
    assert m.insufficient_total == 2
    assert m.insufficient_caught == 1
    assert m.recall_on_insufficient == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 6. per-category breakdown
# ---------------------------------------------------------------------------


def test_per_category_breakdown(tmp_path: Path) -> None:
    """Every Category enum value must appear in the per-category
    accuracy map (even at 0 pairs / 0% accuracy) so Day 4's regression
    report has a stable shape to diff against."""
    gs = _golden()
    pairs = run_calibration(
        verifier=_wire_verifier(gs), golden_set=gs,
        raw_scores_path=tmp_path / "raw.json",
    )
    m = compute_metrics(pairs)
    # All 5 categories present.
    assert set(m.per_category_accuracy.keys()) == {
        "numeric_claim", "causal_claim", "comparative",
        "attribution", "forecast",
    }
    # numeric_claim has 5 pairs in this fixture: t1+t2 correct,
    # t3 wrong (FP), t4 wrong (FN), t5 correct.  3/5 = 0.6.
    assert m.per_category_pair_count["numeric_claim"] == 5
    assert m.per_category_accuracy["numeric_claim"] == pytest.approx(0.6)
    # causal_claim has 1 pair (t6) — verifier said unsupported,
    # ground truth insufficient. unsupported collapses to
    # insufficient in the 5→4 map → 1/1 correct.
    assert m.per_category_pair_count["causal_claim"] == 1
    assert m.per_category_accuracy["causal_claim"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 7. failure cases split FP / FN / other
# ---------------------------------------------------------------------------


def test_failure_cases_split_fp_vs_fn(tmp_path: Path) -> None:
    gs = _golden()
    pairs = run_calibration(
        verifier=_wire_verifier(gs), golden_set=gs,
        raw_scores_path=tmp_path / "raw.json",
    )
    failures = split_failures(pairs)
    fp_ids = {r["id"] for r in failures["false_positives"]}
    fn_ids = {r["id"] for r in failures["false_negatives"]}
    other_ids = {r["id"] for r in failures["other_disagreements"]}
    # t3 is the FP (predicted supported, truth insufficient).
    assert fp_ids == {"t3"}
    # t4 is the FN (predicted not-supported, truth supported).
    assert fn_ids == {"t4"}
    # No "other" disagreements expected in this set.
    assert other_ids == set()
    # FP rows must carry the components Day 3 will need to debug:
    fp_row = failures["false_positives"][0]
    assert "claim_head" in fp_row
    assert "evidence_head" in fp_row
    assert "raw_llm_verdict" in fp_row
    assert "raw_deberta_label" in fp_row
