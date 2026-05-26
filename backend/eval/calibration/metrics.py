"""Calibration metrics — Phase 5 / Week 21 / Day 2.

Pure functions over :class:`ScoredPair` lists. The headline
numbers are:

  - **FP rate on supported** — of every claim the verifier called
    supported, what fraction was actually NOT supported (ground
    truth ≠ supported)? This is the catastrophic-error metric:
    every false-positive lands in a deliverable a partner sees,
    so a high value here means the trust wedge isn't yet
    defendable.
  - **Recall on insufficient** — of every claim that's actually
    insufficient (ground truth = insufficient), what fraction did
    the verifier correctly flag (predicted ∈ {insufficient,
    contradicted, partial})? This is the catch rate that protects
    the wedge. Day 3 tunes thresholds to push it higher without
    blowing up the FP rate.

Plus the breakdown shapes: per-class precision/recall/F1,
per-category accuracy, raw confusion matrix.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from eval.golden_set.types import Category, Verdict

from .runner import ScoredPair


VERDICTS_4 = [v.value for v in Verdict]
CATEGORIES = [c.value for c in Category]


@dataclass
class ClassMetric:
    """Per-class precision / recall / F1 + supports."""

    label: str
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    support: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationMetrics:
    """Top-level metrics shape — what the baseline JSON freezes."""

    pair_count: int
    correct: int
    accuracy: float
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    per_class: list[ClassMetric] = field(default_factory=list)
    per_category_accuracy: dict[str, float] = field(default_factory=dict)
    per_category_pair_count: dict[str, int] = field(default_factory=dict)
    fp_rate_on_supported: float = 0.0
    fp_count_on_supported: int = 0
    supported_predictions: int = 0
    recall_on_insufficient: float = 0.0
    insufficient_caught: int = 0
    insufficient_total: int = 0
    adversarial_accuracy: float = 0.0
    adversarial_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_count": self.pair_count,
            "correct": self.correct,
            "accuracy": self.accuracy,
            "confusion": self.confusion,
            "per_class": [c.to_dict() for c in self.per_class],
            "per_category_accuracy": self.per_category_accuracy,
            "per_category_pair_count": self.per_category_pair_count,
            "fp_rate_on_supported": self.fp_rate_on_supported,
            "fp_count_on_supported": self.fp_count_on_supported,
            "supported_predictions": self.supported_predictions,
            "recall_on_insufficient": self.recall_on_insufficient,
            "insufficient_caught": self.insufficient_caught,
            "insufficient_total": self.insufficient_total,
            "adversarial_accuracy": self.adversarial_accuracy,
            "adversarial_count": self.adversarial_count,
        }


def confusion_matrix(pairs: Iterable[ScoredPair]) -> dict[str, dict[str, int]]:
    """Predicted (rows) × ground-truth (cols). Always a 4×4 dense
    matrix — empty cells are 0, not missing keys — so downstream
    diff'ing is straightforward."""
    matrix: dict[str, dict[str, int]] = {
        pred: {gt: 0 for gt in VERDICTS_4} for pred in VERDICTS_4
    }
    for p in pairs:
        pred = p.ensemble_verdict_collapsed
        gt = p.ground_truth
        if pred in matrix and gt in matrix[pred]:
            matrix[pred][gt] += 1
    return matrix


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _per_class(pairs: list[ScoredPair]) -> list[ClassMetric]:
    """Compute precision/recall/F1 for each of the 4 verdicts."""
    out: list[ClassMetric] = []
    for label in VERDICTS_4:
        tp = sum(
            1 for p in pairs
            if p.ensemble_verdict_collapsed == label and p.ground_truth == label
        )
        fp = sum(
            1 for p in pairs
            if p.ensemble_verdict_collapsed == label and p.ground_truth != label
        )
        fn = sum(
            1 for p in pairs
            if p.ground_truth == label and p.ensemble_verdict_collapsed != label
        )
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        support = sum(1 for p in pairs if p.ground_truth == label)
        out.append(ClassMetric(
            label=label, precision=precision, recall=recall, f1=f1,
            support=support, tp=tp, fp=fp, fn=fn,
        ))
    return out


def _per_category_accuracy(
    pairs: list[ScoredPair],
) -> tuple[dict[str, float], dict[str, int]]:
    acc: dict[str, float] = {}
    counts: dict[str, int] = {}
    for cat in CATEGORIES:
        in_cat = [p for p in pairs if p.category == cat]
        counts[cat] = len(in_cat)
        correct = sum(1 for p in in_cat if p.correct)
        acc[cat] = _safe_div(correct, len(in_cat))
    return acc, counts


def compute_metrics(pairs: Iterable[ScoredPair]) -> CalibrationMetrics:
    """Compute every calibration metric from a flat list of
    scored pairs. Pure function; no I/O."""
    pairs_list = list(pairs)
    n = len(pairs_list)
    correct = sum(1 for p in pairs_list if p.correct)

    # --- headline metrics ---
    supported_preds = [
        p for p in pairs_list if p.ensemble_verdict_collapsed == "supported"
    ]
    fp_on_supported = sum(
        1 for p in supported_preds if p.ground_truth != "supported"
    )
    fp_rate_on_supported = _safe_div(fp_on_supported, len(supported_preds))

    # Recall on insufficient: of all actually-insufficient claims,
    # how many did the verifier classify as not-supported (i.e. caught
    # them, regardless of which not-supported bucket)? The "catch rate."
    insufficient_total = sum(
        1 for p in pairs_list if p.ground_truth == "insufficient"
    )
    insufficient_caught = sum(
        1 for p in pairs_list
        if p.ground_truth == "insufficient"
        and p.ensemble_verdict_collapsed != "supported"
    )
    recall_on_insufficient = _safe_div(insufficient_caught, insufficient_total)

    # --- adversarial slice ---
    adv = [p for p in pairs_list if p.adversarial]
    adv_correct = sum(1 for p in adv if p.correct)

    return CalibrationMetrics(
        pair_count=n,
        correct=correct,
        accuracy=_safe_div(correct, n),
        confusion=confusion_matrix(pairs_list),
        per_class=_per_class(pairs_list),
        per_category_accuracy=_per_category_accuracy(pairs_list)[0],
        per_category_pair_count=_per_category_accuracy(pairs_list)[1],
        fp_rate_on_supported=fp_rate_on_supported,
        fp_count_on_supported=fp_on_supported,
        supported_predictions=len(supported_preds),
        recall_on_insufficient=recall_on_insufficient,
        insufficient_caught=insufficient_caught,
        insufficient_total=insufficient_total,
        adversarial_accuracy=_safe_div(adv_correct, len(adv)),
        adversarial_count=len(adv),
    )


def split_failures(
    pairs: Iterable[ScoredPair],
) -> dict[str, list[dict[str, Any]]]:
    """Split disagreements into false-positives + false-negatives +
    other (e.g. predicted partial when truth is insufficient). Each
    row is the small audit dict an operator wants to read; we
    redact claim/evidence text to short heads (≤120 chars) so the
    failure surface stays readable without dumping prose blobs."""
    fp: list[dict[str, Any]] = []
    fn: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for p in pairs:
        if p.correct:
            continue
        row = {
            "id": p.id,
            "category": p.category,
            "adversarial": p.adversarial,
            "ground_truth": p.ground_truth,
            "ensemble_verdict": p.ensemble_verdict,
            "ensemble_verdict_collapsed": p.ensemble_verdict_collapsed,
            "reason": p.reason,
            "claim_head": (p.claim or "")[:120],
            "evidence_head": (p.evidence or "")[:120],
            "raw_llm_verdict": p.raw.llm_verdict,
            "raw_deberta_label": p.raw.deberta_label,
            "raw_deberta_confidence": round(p.raw.deberta_confidence, 3),
            "raw_lexical_numeric_score": round(p.raw.lexical_numeric_score, 3),
        }
        if p.error_kind == "false_positive":
            fp.append(row)
        elif p.error_kind == "false_negative":
            fn.append(row)
        else:
            other.append(row)
    return {
        "false_positives": fp,
        "false_negatives": fn,
        "other_disagreements": other,
    }


__all__ = [
    "CalibrationMetrics",
    "ClassMetric",
    "compute_metrics",
    "confusion_matrix",
    "split_failures",
]
