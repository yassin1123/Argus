"""Tests for the W22/D2 signal-bottleneck diagnoser.

Five spec assertions:

  1. every false-positive is decomposed by component (LLM /
     DeBERTa / lexical / aggregation / evidence)
  2. each FP is classified as signal-fault OR evidence-fault
  3. evidence-quality audit is produced for the FP set
  4. component-agreement analysis is computed
  5. the highest-leverage fix target is named — including the
     ``multi_front`` disposition when no fault dominates
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core.nli.threshold_config import default_threshold_config  # noqa: E402
from eval.calibration.diagnose import (  # noqa: E402
    FAULT_AGGREGATION,
    FAULT_DEBERTA,
    FAULT_EVIDENCE,
    FAULT_LEXICAL_FALSE_FRIEND,
    FAULT_LLM_ENTAILMENT,
    diagnose,
    write_diagnosis,
)
from eval.calibration.runner import RawScores, ScoredPair  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _pair(
    eid: str, *,
    gt: str,
    llm: str = "supported",
    deberta_label: str = "entailment",
    deberta_conf: float = 0.85,
    lex_num: float = 1.0,
    ensemble: str = "supported_high",
    category: str = "numeric_claim",
    claim: str = "claim text",
    evidence: str = "evidence text",
) -> ScoredPair:
    raw = RawScores(
        llm_verdict=llm,
        deberta_label=deberta_label,
        deberta_confidence=deberta_conf,
        deberta_softmax=(0.05, 0.85, 0.10),
        lexical_numeric_score=lex_num,
        lexical_entity_score=1.0,
    )
    collapsed = "supported" if ensemble.startswith("supported") else (
        "contradicted" if ensemble == "contradicted" else
        "insufficient" if ensemble == "unsupported" else "partial"
    )
    return ScoredPair(
        id=eid, claim=claim, evidence=evidence,
        category=category, adversarial=False,
        ground_truth=gt,
        ensemble_verdict=ensemble,
        ensemble_verdict_collapsed=collapsed,
        reason="test",
        raw=raw,
        correct=(collapsed == gt),
        error_kind=None,
    )


# ---------------------------------------------------------------------------
# 1. per-component decomposition
# ---------------------------------------------------------------------------


def test_fp_cases_decomposed_by_component() -> None:
    """Each FP has a primary_fault categorising the misfire +
    a components dict capturing the raw scores. We plant four
    FPs with different patterns + assert the diagnoser names
    each one correctly."""
    pairs = [
        # Evidence fault: insufficient + clean signals.
        _pair("ev1", gt="insufficient", llm="supported",
              deberta_label="entailment", deberta_conf=0.85, lex_num=1.0),
        # DeBERTa fault: contradicted truth + DeBERTa entailment.
        _pair("db1", gt="contradicted", llm="supported",
              deberta_label="entailment", deberta_conf=0.85, lex_num=1.0),
        # Lexical false-friend: partial truth + lex=1.0.
        _pair("lx1", gt="partial", llm="supported",
              deberta_label="entailment", deberta_conf=0.85, lex_num=1.0),
        # Aggregation fault: LLM=supported but DeBERTa low-conf.
        _pair("ag1", gt="insufficient", llm="supported",
              deberta_label="entailment", deberta_conf=0.40, lex_num=1.0),
    ]
    report = diagnose(pairs)
    assert report["false_positive_count"] == 4
    by_id = {d["id"]: d for d in report["fp_diagnoses"]}

    # Aggregation fault takes priority (a component dissented).
    assert by_id["ag1"]["primary_fault"] == FAULT_AGGREGATION

    # The non-aggregation cases pick their primary fault by ground
    # truth + component pattern.
    assert by_id["ev1"]["primary_fault"] == FAULT_EVIDENCE
    assert by_id["db1"]["primary_fault"] == FAULT_DEBERTA
    assert by_id["lx1"]["primary_fault"] == FAULT_LEXICAL_FALSE_FRIEND

    # Every diagnosis carries the raw component scores so an
    # operator reviewing the JSON sees what fired.
    for d in report["fp_diagnoses"]:
        c = d["components"]
        assert "llm_verdict" in c
        assert "deberta_label" in c
        assert "deberta_confidence" in c
        assert "lexical_numeric_score" in c


# ---------------------------------------------------------------------------
# 2. signal vs evidence classification
# ---------------------------------------------------------------------------


def test_fault_classification_signal_vs_evidence() -> None:
    """The evidence_audit panel reports the signal-vs-evidence
    split + an interpretation. When most FPs are signal-faults the
    interpretation is ``signal_fault``; when the evidence column
    dominates, ``evidence_fault``."""
    # 3 signal-faults (db / lx / agg) + 1 evidence-fault.
    pairs = [
        _pair("ev1", gt="insufficient", lex_num=1.0),
        _pair("db1", gt="contradicted"),
        _pair("lx1", gt="partial"),
        _pair("ag1", gt="insufficient", deberta_conf=0.4),
    ]
    report = diagnose(pairs)
    ea = report["evidence_audit"]
    assert ea["signal_fault_count"] == 3
    assert ea["evidence_fault_count"] == 1
    assert ea["interpretation"] == "signal_fault"

    # Flip the balance: 3 evidence faults, 1 signal fault.
    flipped = [
        _pair(f"ev{i}", gt="insufficient", lex_num=1.0)
        for i in range(3)
    ] + [_pair("db1", gt="contradicted")]
    report = diagnose(flipped)
    ea = report["evidence_audit"]
    assert ea["evidence_fault_count"] == 3
    assert ea["signal_fault_count"] == 1
    assert ea["interpretation"] == "evidence_fault"


# ---------------------------------------------------------------------------
# 3. evidence-quality audit
# ---------------------------------------------------------------------------


def test_evidence_quality_audited_for_fps() -> None:
    """For every evidence-fault FP, the audit panel carries the
    claim_head + evidence_head so an operator can sanity-check
    whether the chunk really fails to address the claim."""
    pairs = [
        _pair("ev1", gt="insufficient", lex_num=1.0,
              claim="Revenue grew 12% in FY2023",
              evidence="FY2023 results were presented at the AGM"),
        _pair("ev2", gt="insufficient", lex_num=1.0,
              claim="EBITDA margin expanded 220 bps",
              evidence="Margin trajectory was discussed in the CFO commentary"),
    ]
    report = diagnose(pairs)
    samples = report["evidence_audit"]["evidence_fault_samples"]
    assert len(samples) == 2
    for s in samples:
        assert "claim_head" in s
        assert "evidence_head" in s
        assert "ground_truth" in s
        assert s["claim_head"]
        assert s["evidence_head"]
    # The audit fraction reflects the share of FPs that are
    # evidence-fault (here: 2/2 = 1.0).
    assert report["evidence_audit"]["evidence_fault_fraction"] == 1.0


# ---------------------------------------------------------------------------
# 4. component agreement
# ---------------------------------------------------------------------------


def test_component_agreement_analysis() -> None:
    """The agreement panel reports all-yes / all-no / disagree
    counts + which component called it correctly when in the
    minority."""
    pairs = [
        # All three say "supported"; truth is supported → all-yes
        # cases stack up.
        _pair("s1", gt="supported", llm="supported",
              deberta_label="entailment", deberta_conf=0.85, lex_num=1.0),
        _pair("s2", gt="supported", llm="supported",
              deberta_label="entailment", deberta_conf=0.85, lex_num=1.0),
        # All three say not-supported.
        _pair("n1", gt="insufficient", llm="unsupported",
              deberta_label="neutral", deberta_conf=0.40,
              lex_num=0.5, ensemble="unsupported"),
        # Disagreement: LLM + DeBERTa say supported, lex flags drift
        # (score < drift threshold) → lex is the minority voice.
        # Truth is partial — so the lex minority called it right.
        _pair("d1", gt="partial", llm="supported",
              deberta_label="entailment", deberta_conf=0.85,
              lex_num=0.3, ensemble="supported_low"),
    ]
    report = diagnose(pairs)
    a = report["component_agreement"]
    assert a["all_three_agree_supported"] == 2
    assert a["all_three_agree_not_supported"] == 1
    assert a["disagreement_cases"] == 1
    # Lex was the dissenter in the d1 case + called it right
    # (partial truth, lex flagged drift). Reliability rolls up
    # at the per-component level too.
    minority = a["minority_correctly_called_when_disagree"]
    assert minority.get("lexical", 0) >= 1
    # component_reliability is a list with one entry per component.
    rel_by_name = {c["component"]: c for c in report["component_reliability"]}
    assert set(rel_by_name.keys()) == {"llm", "deberta", "lexical"}
    for c in rel_by_name.values():
        assert "correct" in c
        assert "samples" in c
        assert 0.0 <= c["reliability"] <= 1.0


# ---------------------------------------------------------------------------
# 5. highest-leverage target named
# ---------------------------------------------------------------------------


def test_highest_leverage_target_identified(tmp_path: Path) -> None:
    """When a single fault category dominates, the target names
    the specific fix (LLM prompt / DeBERTa / aggregator /
    retrieval). When faults split with no dominant one, the
    target is ``multi_front`` per the W22/D2 spec."""

    # Case A — single dominant fault: 4 evidence-fault FPs only.
    dominant = [
        _pair(f"ev{i}", gt="insufficient", lex_num=1.0) for i in range(4)
    ]
    report = diagnose(dominant)
    h = report["highest_leverage_target"]
    assert h["target"] == "evidence_retrieval_and_selection"
    assert h["dominant_fault"] == FAULT_EVIDENCE
    assert h["dominant_fault_share"] >= 0.5

    # Case B — multi-front: 4 different fault categories, 1 each.
    multi = [
        _pair("ev1", gt="insufficient", lex_num=1.0),
        _pair("db1", gt="contradicted"),
        _pair("lx1", gt="partial"),
        _pair("ag1", gt="insufficient", deberta_conf=0.4),
    ]
    report = diagnose(multi)
    h = report["highest_leverage_target"]
    assert h["target"] == "multi_front"
    assert "multi-front" in h["rationale"].lower()

    # End-to-end: write_diagnosis dumps a JSON payload carrying
    # all the panels.
    from eval.calibration.runner import RawScores
    # Build a tiny raw_scores.json the runner can replay.
    pair_rows = []
    for p in multi:
        pair_rows.append({
            "id": p.id, "claim": p.claim, "evidence": p.evidence,
            "category": p.category, "adversarial": p.adversarial,
            "ground_truth": p.ground_truth,
            "ensemble_verdict": p.ensemble_verdict,
            "ensemble_verdict_collapsed": p.ensemble_verdict_collapsed,
            "reason": p.reason,
            "raw": p.raw.to_dict(),
            "correct": p.correct, "error_kind": p.error_kind,
        })
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps({
        "verifier_source": "test",
        "pair_count": len(pair_rows),
        "scored_pairs": pair_rows,
    }))
    out_path = tmp_path / "summary.json"
    end_to_end = write_diagnosis(raw_path=raw_path, out_path=out_path)
    assert out_path.exists()
    loaded = json.loads(out_path.read_text())
    # The dumped JSON carries the same panels as the in-memory dict.
    for key in (
        "false_positive_count", "fault_distribution",
        "fp_diagnoses", "evidence_audit",
        "component_reliability", "component_agreement",
        "highest_leverage_target",
    ):
        assert key in loaded
    assert loaded["highest_leverage_target"]["target"] == "multi_front"
