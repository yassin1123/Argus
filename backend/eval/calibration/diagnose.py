"""Signal-bottleneck diagnoser — Phase 5 / Week 22 / Day 2.

For each false-positive (predicted supported, truth ≠ supported),
decompose which ensemble component(s) misfired. The headline
question this answers: **is the bottleneck a signal problem
(components judge wrongly) or an evidence problem (components
judge what they saw correctly, but they were given the wrong
evidence)?**

The diagnoser is a pure analyser over the cached raw scores
(W21/D2 raw_scores.json + W22/D1 raw_scores_real.json). No LLM
calls. No retraining. Today is diagnosis only — the W21
discipline of *diagnose before fixing* applies.

Output: ``backend/eval_runs/week22_diagnosis/summary.json`` —
named in the report which component or stage is the highest-
leverage fix target, with a one-line rationale.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from core.nli.threshold_config import (
    ThresholdConfig,
    default_threshold_config,
)
from eval.calibration.runner import (
    RawScores,
    ScoredPair,
    load_scored_pairs,
)
from eval.golden_set.types import collapse_verdict

logger = logging.getLogger(__name__)


_BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_RAW_SCORES = (
    _BACKEND / "eval" / "calibration" / "raw_scores.json"
)
DEFAULT_OUT = (
    _BACKEND / "eval_runs" / "week22_diagnosis" / "summary.json"
)


# ---------------------------------------------------------------------------
# Fault taxonomy
# ---------------------------------------------------------------------------


# Five fault types — the W22/D2 spec's classification. Each FP
# row gets a primary fault + (optionally) a secondary one. The
# diagnosis report groups by primary fault to surface the
# dominant pattern.

FAULT_LLM_ENTAILMENT = "llm_entailment_fault"
FAULT_DEBERTA = "deberta_fault"
FAULT_LEXICAL_FALSE_FRIEND = "lexical_false_friend"
FAULT_AGGREGATION = "aggregation_fault"
FAULT_EVIDENCE = "evidence_fault"

FAULT_LABELS: dict[str, str] = {
    FAULT_LLM_ENTAILMENT:    "LLM-entailment fault",
    FAULT_DEBERTA:           "DeBERTa fault",
    FAULT_LEXICAL_FALSE_FRIEND: "Lexical false-friend",
    FAULT_AGGREGATION:       "Aggregation fault",
    FAULT_EVIDENCE:          "Evidence fault (wrong/insufficient chunk)",
}


# ---------------------------------------------------------------------------
# Per-FP classification
# ---------------------------------------------------------------------------


@dataclass
class FaultDiagnosis:
    """One FP's decomposition."""

    id: str
    ground_truth: str
    ensemble_verdict: str
    primary_fault: str
    secondary_faults: list[str] = field(default_factory=list)
    rationale: str = ""
    components: dict[str, Any] = field(default_factory=dict)
    claim_head: str = ""
    evidence_head: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _classify_fault(
    pair: ScoredPair, config: ThresholdConfig,
) -> FaultDiagnosis:
    """Decide which component(s) misfired on this FP.

    The classifier is rule-based; the rules encode the spec's
    fault taxonomy.

      - **DeBERTa fault** — entailment + high confidence but the
        claim is contradicted (the NLI model should have caught
        direction reversal). Always paired with LLM fault when
        the LLM also passed.
      - **LLM-entailment fault** — LLM said supported but the
        case demands semantic structure the LLM missed
        (conjunctive claims, causal claims, attribution).
      - **Lexical false-friend** — lex score == 1.0 (no drift
        detected) but the claim's truth depends on a non-
        numeric/non-entity assertion. The lexical signal can
        only catch numeric/entity drift; it has nothing to say
        about causal/semantic claims.
      - **Aggregation fault** — the components individually
        gave reasonable signals but the aggregator combined
        them wrong. Detected when one component flagged a
        concern (e.g. low DeBERTa confidence, or numeric drift)
        but the aggregator still produced supported_*.
      - **Evidence fault** — every component scored the
        (claim, evidence) pair correctly under what they saw,
        but the evidence shown DOES support a more general
        version of the claim while not establishing the specific
        assertion. Detected when truth is *insufficient* (chunk
        is topically right but doesn't address the specific
        assertion) and every component scored consistent with
        the chunk's content.
    """
    raw = pair.raw
    truth = pair.ground_truth
    llm_v = (raw.llm_verdict or "").strip().lower()
    db_label = (raw.deberta_label or "").strip().lower()
    db_conf = float(raw.deberta_confidence or 0.0)
    lex_num = float(raw.lexical_numeric_score or 0.0)
    high_conf = float(config.deberta_high_conf)
    drift = float(config.numeric_drift_below)

    primary = ""
    secondaries: list[str] = []

    # ---- Aggregation fault first — if any component signalled
    # concern but the aggregator still produced supported. ----
    db_low_conf = db_label == "entailment" and db_conf < high_conf
    lex_drift = lex_num < drift
    db_neutral_or_contra = db_label in {"neutral", "contradiction", "unknown"}
    if (db_low_conf or lex_drift or db_neutral_or_contra) and llm_v == "supported":
        # At least one component dissented but the aggregator still
        # landed on supported_*. That's an aggregation bug, not a
        # component bug.
        primary = FAULT_AGGREGATION
        return FaultDiagnosis(
            id=pair.id, ground_truth=truth,
            ensemble_verdict=pair.ensemble_verdict,
            primary_fault=primary,
            secondary_faults=secondaries,
            rationale=(
                "components dissented (deberta_label="
                f"{db_label}, conf={db_conf:.2f}, lex_num={lex_num:.2f}) "
                "but the aggregator still produced "
                f"{pair.ensemble_verdict}. Re-weighting / re-thresholding "
                "the aggregator is the fix path, not the component models."
            ),
            components={
                "llm_verdict": raw.llm_verdict,
                "deberta_label": raw.deberta_label,
                "deberta_confidence": round(db_conf, 3),
                "lexical_numeric_score": round(lex_num, 3),
            },
            claim_head=(pair.claim or "")[:140],
            evidence_head=(pair.evidence or "")[:140],
        )

    # ---- Direction-reversal cases — primary fault is DeBERTa +
    # LLM both missing a contradiction. ----
    if truth == "contradicted":
        primary = FAULT_DEBERTA
        if llm_v == "supported":
            secondaries.append(FAULT_LLM_ENTAILMENT)
        rationale = (
            "ground truth is contradicted but DeBERTa labelled "
            f"{db_label!r} at conf {db_conf:.2f}. The cross-encoder "
            "should have flagged contradiction; this is a model-"
            "reliability question, not a threshold one."
        )
        return FaultDiagnosis(
            id=pair.id, ground_truth=truth,
            ensemble_verdict=pair.ensemble_verdict,
            primary_fault=primary,
            secondary_faults=secondaries,
            rationale=rationale,
            components={
                "llm_verdict": raw.llm_verdict,
                "deberta_label": raw.deberta_label,
                "deberta_confidence": round(db_conf, 3),
                "lexical_numeric_score": round(lex_num, 3),
            },
            claim_head=(pair.claim or "")[:140],
            evidence_head=(pair.evidence or "")[:140],
        )

    # ---- Insufficient ground truth + clean signals = evidence
    # fault. The chunk likely doesn't contain the specific
    # assertion; the verifier judged what it saw, but it saw
    # the wrong thing. ----
    if truth == "insufficient" and lex_num >= 1.0 - 1e-6:
        primary = FAULT_EVIDENCE
        rationale = (
            "every component scored consistent with the chunk "
            "(LLM=supported, deberta=entailment, lex=1.0) yet the "
            "ground truth is insufficient — the chunk is topically "
            "related but doesn't establish the specific assertion. "
            "Retrieval / evidence-selection is the fix target, "
            "not the verifier signals themselves."
        )
        return FaultDiagnosis(
            id=pair.id, ground_truth=truth,
            ensemble_verdict=pair.ensemble_verdict,
            primary_fault=primary,
            secondary_faults=secondaries,
            rationale=rationale,
            components={
                "llm_verdict": raw.llm_verdict,
                "deberta_label": raw.deberta_label,
                "deberta_confidence": round(db_conf, 3),
                "lexical_numeric_score": round(lex_num, 3),
            },
            claim_head=(pair.claim or "")[:140],
            evidence_head=(pair.evidence or "")[:140],
        )

    # ---- Partial ground truth — usually a conjunctive /
    # magnitude / cherry-pick claim. Lexical can't catch
    # semantic structure; if lex is clean here, that's a
    # false-friend. ----
    if truth == "partial":
        if lex_num >= 1.0 - 1e-6:
            primary = FAULT_LEXICAL_FALSE_FRIEND
            secondaries.append(FAULT_LLM_ENTAILMENT)
            rationale = (
                "ground truth is partial (claim asserts more than the "
                "evidence supports) but lex=1.0 — the lexical signal "
                "doesn't catch semantic / conjunctive overclaims. "
                "LLM judge prompt-tightening is the secondary fix; "
                "lexical signal cannot be tuned to fix this class."
            )
        else:
            # Numeric drift detected by lexical but aggregator
            # still let it through — aggregation fault already
            # handled above, so this is an LLM fault.
            primary = FAULT_LLM_ENTAILMENT
            rationale = (
                "lex flagged numeric drift but LLM voted supported. "
                "LLM judge missed the magnitude / partial mismatch."
            )
        return FaultDiagnosis(
            id=pair.id, ground_truth=truth,
            ensemble_verdict=pair.ensemble_verdict,
            primary_fault=primary,
            secondary_faults=secondaries,
            rationale=rationale,
            components={
                "llm_verdict": raw.llm_verdict,
                "deberta_label": raw.deberta_label,
                "deberta_confidence": round(db_conf, 3),
                "lexical_numeric_score": round(lex_num, 3),
            },
            claim_head=(pair.claim or "")[:140],
            evidence_head=(pair.evidence or "")[:140],
        )

    # ---- Catch-all: LLM said supported, everything else agreed,
    # truth was wrong → LLM-entailment fault. ----
    primary = FAULT_LLM_ENTAILMENT
    rationale = (
        "components agreed on supported but ground truth was "
        f"{truth}. LLM judge's interpretation was wrong; the other "
        "components followed."
    )
    return FaultDiagnosis(
        id=pair.id, ground_truth=truth,
        ensemble_verdict=pair.ensemble_verdict,
        primary_fault=primary,
        secondary_faults=secondaries,
        rationale=rationale,
        components={
            "llm_verdict": raw.llm_verdict,
            "deberta_label": raw.deberta_label,
            "deberta_confidence": round(db_conf, 3),
            "lexical_numeric_score": round(lex_num, 3),
        },
        claim_head=(pair.claim or "")[:140],
        evidence_head=(pair.evidence or "")[:140],
    )


# ---------------------------------------------------------------------------
# Component reliability analysis
# ---------------------------------------------------------------------------


@dataclass
class ComponentReliability:
    """How often each component is "right" — i.e. its signal
    aligns with ground truth."""

    component: str
    samples: int = 0
    correct: int = 0
    incorrect: int = 0
    silent: int = 0
    reliability: float = 0.0   # correct / samples

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _llm_says_supported(raw: RawScores) -> bool:
    return (raw.llm_verdict or "").strip().lower() == "supported"


def _deberta_says_entail(raw: RawScores, config: ThresholdConfig) -> bool:
    return (
        (raw.deberta_label or "").strip().lower() == "entailment"
        and float(raw.deberta_confidence or 0.0)
        >= float(config.deberta_high_conf)
    )


def _lexical_clean(raw: RawScores, config: ThresholdConfig) -> bool:
    return float(raw.lexical_numeric_score or 0.0) >= float(
        config.numeric_drift_below
    )


def _component_reliability(
    pairs: list[ScoredPair], config: ThresholdConfig,
) -> list[ComponentReliability]:
    """For each component: how often does it agree with ground
    truth?

      - LLM:     ``llm_verdict==supported`` should match
        ``ground_truth==supported``.
      - DeBERTa: high-confidence ``entailment`` should match
        ``ground_truth==supported``; ``contradiction`` should
        match ``contradicted``.
      - Lexical: ``score==1.0`` should be consistent with
        ``supported``/``partial`` (the lexical signal is precision-
        only, so we score it as "doesn't drift when claim is
        supported" — the false-friend pattern surfaces in the
        per-FP classifier, not here).
    """
    counters: dict[str, ComponentReliability] = {
        "llm": ComponentReliability(component="llm"),
        "deberta": ComponentReliability(component="deberta"),
        "lexical": ComponentReliability(component="lexical"),
    }
    for p in pairs:
        is_supported_truth = p.ground_truth == "supported"

        # LLM: "supported" vote should align with supported truth.
        llm_supp = _llm_says_supported(p.raw)
        counters["llm"].samples += 1
        if llm_supp == is_supported_truth:
            counters["llm"].correct += 1
        else:
            counters["llm"].incorrect += 1

        # DeBERTa: entailment+high-conf should align with supported.
        db_entail = _deberta_says_entail(p.raw, config)
        # Treat "neutral" or low-confidence entailment as silent —
        # the component declined to commit.
        if (
            (p.raw.deberta_label or "").lower() == "entailment"
            and float(p.raw.deberta_confidence or 0.0)
            < float(config.deberta_high_conf)
        ):
            counters["deberta"].silent += 1
        elif (p.raw.deberta_label or "").lower() == "neutral":
            counters["deberta"].silent += 1
        else:
            counters["deberta"].samples += 1
            if db_entail == is_supported_truth:
                counters["deberta"].correct += 1
            else:
                counters["deberta"].incorrect += 1

        # Lexical: lex==1.0 (no drift) on supported is "right";
        # lex<1.0 (drift flagged) on non-supported is "right".
        lex_clean = _lexical_clean(p.raw, config)
        counters["lexical"].samples += 1
        # Define correctness as: "lex flags drift iff claim is not supported."
        flagged_drift = not lex_clean
        wants_flag = not is_supported_truth
        if flagged_drift == wants_flag:
            counters["lexical"].correct += 1
        else:
            counters["lexical"].incorrect += 1

    for c in counters.values():
        denom = c.samples if c.samples > 0 else 1
        c.reliability = round(c.correct / denom, 4)
    return list(counters.values())


# ---------------------------------------------------------------------------
# Agreement analysis
# ---------------------------------------------------------------------------


def _agreement(
    pairs: list[ScoredPair], config: ThresholdConfig,
) -> dict[str, Any]:
    """Three-way agreement matrix + who's typically right when
    they disagree."""
    agree_all_yes = 0       # all three say "supported"
    agree_all_no = 0        # all three say "not supported"
    disagree = 0
    minority_right_counts: Counter[str] = Counter()

    for p in pairs:
        llm = _llm_says_supported(p.raw)
        deb = _deberta_says_entail(p.raw, config)
        lex = _lexical_clean(p.raw, config)
        votes = (llm, deb, lex)
        if all(votes):
            agree_all_yes += 1
        elif not any(votes):
            agree_all_no += 1
        else:
            disagree += 1
            is_supp = p.ground_truth == "supported"
            # On a disagreement, the "minority" is whichever component
            # voted *opposite* to the majority. Record which voice
            # called the case correctly.
            yes_votes = sum(1 for v in votes if v)
            majority_yes = yes_votes >= 2
            # Component k voted "minority" if its vote != majority.
            comp_names = ("llm", "deberta", "lexical")
            for name, v in zip(comp_names, votes):
                in_majority = (v == majority_yes)
                if in_majority:
                    continue
                # Minority called the case correctly iff its
                # vote aligns with the truth.
                if v == is_supp:
                    minority_right_counts[name] += 1
    return {
        "all_three_agree_supported": agree_all_yes,
        "all_three_agree_not_supported": agree_all_no,
        "disagreement_cases": disagree,
        "minority_correctly_called_when_disagree": dict(minority_right_counts),
    }


# ---------------------------------------------------------------------------
# Evidence-quality audit
# ---------------------------------------------------------------------------


def _evidence_audit(
    fp_diagnoses: list[FaultDiagnosis],
) -> dict[str, Any]:
    """Of every FP, how many were classified as evidence faults
    vs signal faults? + a small sample of evidence heads from
    the evidence-fault cases so the operator can sanity-check
    whether the chunks really did fail to address the claim."""
    by_kind: Counter[str] = Counter()
    for d in fp_diagnoses:
        by_kind["evidence" if d.primary_fault == FAULT_EVIDENCE else "signal"] += 1
    evidence_samples = [
        {
            "id": d.id,
            "claim_head": d.claim_head,
            "evidence_head": d.evidence_head,
            "ground_truth": d.ground_truth,
        }
        for d in fp_diagnoses
        if d.primary_fault == FAULT_EVIDENCE
    ][:5]
    total = sum(by_kind.values()) or 1
    return {
        "signal_fault_count": by_kind["signal"],
        "evidence_fault_count": by_kind["evidence"],
        "evidence_fault_fraction": round(
            by_kind["evidence"] / total, 4,
        ),
        "evidence_fault_samples": evidence_samples,
        "interpretation": (
            "evidence_fault" if by_kind["evidence"] >= by_kind["signal"]
            else "signal_fault"
        ),
    }


# ---------------------------------------------------------------------------
# Highest-leverage target
# ---------------------------------------------------------------------------


def _name_highest_leverage_target(
    fault_counts: dict[str, int],
    evidence_audit: dict[str, Any],
    component_reliability: list[ComponentReliability],
) -> dict[str, Any]:
    """Pick THE single highest-leverage fix target."""
    if not fault_counts:
        return {
            "target": "none",
            "rationale": (
                "no false positives in the analysed set — "
                "there's nothing to diagnose. The trust signal is "
                "already clean against this fixture."
            ),
        }
    dominant_fault, dominant_count = max(
        fault_counts.items(), key=lambda kv: kv[1],
    )
    total = sum(fault_counts.values())
    dominant_share = dominant_count / max(1, total)

    # If no fault type dominates, the W22/D2 spec says to flag a
    # multi-front problem honestly.
    if dominant_share < 0.5 and total > 2:
        return {
            "target": "multi_front",
            "rationale": (
                "FPs split across multiple fault types with no dominant "
                "one (top fault = "
                f"{FAULT_LABELS[dominant_fault]} at {dominant_share:.0%}). "
                "This is a harder, multi-front problem; the week's "
                "expectations adjust + each fault type gets its own "
                "incremental fix in Days 3-5."
            ),
            "fault_distribution": fault_counts,
        }

    # Map fault category → fix target.
    target_map: dict[str, tuple[str, str]] = {
        FAULT_LLM_ENTAILMENT: (
            "llm_judge_prompt_tightening",
            "the LLM judge is consistently wrong on these claims. "
            "Tighten its prompt to attend to the semantic structure "
            "(conjunctive claims, magnitude, attribution).",
        ),
        FAULT_DEBERTA: (
            "deberta_model_or_threshold_re_evaluation",
            "the cross-encoder is missing contradictions. Either the "
            "model needs to be swapped (a different NLI checkpoint) or "
            "the contradiction-veto threshold needs lowering.",
        ),
        FAULT_LEXICAL_FALSE_FRIEND: (
            "lexical_signal_is_topped_out",
            "lex=1.0 fires when the claim has no numerics, so lex "
            "cannot help on semantic / conjunctive FPs. The LLM "
            "judge prompt is the only path; don't tune lexical here.",
        ),
        FAULT_AGGREGATION: (
            "aggregator_re_weighting",
            "components were dissenting but the aggregator combined them "
            "wrong. Re-thresholding or re-weighting the aggregator is "
            "the path; the component models are fine.",
        ),
        FAULT_EVIDENCE: (
            "evidence_retrieval_and_selection",
            "the verifier was given the wrong evidence span. The fix "
            "lives upstream of the verifier — retrieval re-ranking, "
            "chunk granularity, or claim-specific evidence selection.",
        ),
    }
    target_name, rationale = target_map[dominant_fault]
    return {
        "target": target_name,
        "dominant_fault": dominant_fault,
        "dominant_fault_label": FAULT_LABELS[dominant_fault],
        "dominant_fault_count": dominant_count,
        "dominant_fault_share": round(dominant_share, 3),
        "rationale": rationale,
        "fault_distribution": fault_counts,
        "evidence_interpretation": evidence_audit["interpretation"],
    }


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def diagnose(
    pairs: Iterable[ScoredPair],
    *,
    config: ThresholdConfig | None = None,
) -> dict[str, Any]:
    """Pure analyser. Returns the full diagnosis dict the report
    writes to JSON."""
    cfg = config or default_threshold_config()
    pair_list = list(pairs)

    # Identify FPs against ground truth + the collapsed verdict.
    fp_pairs = [
        p for p in pair_list
        if collapse_verdict(p.ensemble_verdict) == "supported"
        and p.ground_truth != "supported"
    ]
    fp_diagnoses = [_classify_fault(p, cfg) for p in fp_pairs]
    fault_counts: dict[str, int] = dict(
        Counter(d.primary_fault for d in fp_diagnoses)
    )

    reliability = _component_reliability(pair_list, cfg)
    agreement = _agreement(pair_list, cfg)
    evidence_audit = _evidence_audit(fp_diagnoses)
    leverage = _name_highest_leverage_target(
        fault_counts, evidence_audit, reliability,
    )

    return {
        "total_pairs": len(pair_list),
        "false_positive_count": len(fp_diagnoses),
        "fault_distribution": fault_counts,
        "fp_diagnoses": [d.to_dict() for d in fp_diagnoses],
        "evidence_audit": evidence_audit,
        "component_reliability": [r.to_dict() for r in reliability],
        "component_agreement": agreement,
        "highest_leverage_target": leverage,
        "config_used": cfg.to_dict(),
    }


def write_diagnosis(
    *,
    raw_path: Path | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """End-to-end: load cached pairs, diagnose, write JSON."""
    rp = raw_path or DEFAULT_RAW_SCORES
    if not rp.exists():
        raise FileNotFoundError(
            f"raw scores cache missing at {rp}; "
            "run W21/D2 calibration first"
        )
    pairs = load_scored_pairs(rp)
    report = diagnose(pairs)
    report["raw_scores_path"] = str(rp)
    out = out_path or DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default=str(DEFAULT_RAW_SCORES))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    report = write_diagnosis(
        raw_path=Path(args.raw), out_path=Path(args.out),
    )

    print()
    print("=== W22/D2 signal-bottleneck diagnosis ===")
    print(f"  total pairs analysed: {report['total_pairs']}")
    print(f"  false positives:      {report['false_positive_count']}")
    if report["false_positive_count"]:
        print()
        print("  fault distribution:")
        for k, v in report["fault_distribution"].items():
            print(f"    {FAULT_LABELS.get(k, k):42s} {v}")

    ea = report["evidence_audit"]
    print()
    print(f"  signal vs evidence:")
    print(f"    signal-fault FPs:   {ea['signal_fault_count']}")
    print(f"    evidence-fault FPs: {ea['evidence_fault_count']}")
    print(f"    -> interpretation: {ea['interpretation']}")

    print()
    print("  component reliability (correct / samples):")
    for c in report["component_reliability"]:
        print(f"    {c['component']:8s}  "
              f"{c['correct']}/{c['samples']}  "
              f"({c['reliability']:.0%})  silent={c['silent']}")

    print()
    a = report["component_agreement"]
    print("  three-way agreement:")
    print(f"    all yes: {a['all_three_agree_supported']}  "
          f"all no: {a['all_three_agree_not_supported']}  "
          f"disagree: {a['disagreement_cases']}")
    if a["minority_correctly_called_when_disagree"]:
        print(f"    minority-correct-when-disagree: "
              f"{a['minority_correctly_called_when_disagree']}")

    print()
    h = report["highest_leverage_target"]
    print(f"  HIGHEST-LEVERAGE TARGET: {h['target']}")
    print(f"  {h['rationale']}")
    print()
    print(f"  diagnosis -> {args.out}")
    return 0


__all__ = [
    "DEFAULT_OUT",
    "DEFAULT_RAW_SCORES",
    "FAULT_AGGREGATION",
    "FAULT_DEBERTA",
    "FAULT_EVIDENCE",
    "FAULT_LABELS",
    "FAULT_LEXICAL_FALSE_FRIEND",
    "FAULT_LLM_ENTAILMENT",
    "FaultDiagnosis",
    "diagnose",
    "write_diagnosis",
]


if __name__ == "__main__":
    raise SystemExit(main())
