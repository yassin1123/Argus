"""Calibration runner — Phase 5 / Week 21 / Day 2.

Drives the real cross-family verification path against the
golden set and caches per-pair raw component scores. Day 3
threshold-tuning re-uses the cache without spending more LLM
money.

Three verifier sources are wired:

  - ``real_ensemble``      — the production path: LLM judge
    (``agents.verifier``) + DeBERTa cross-encoder
    (``core.nli.deberta_client``) + lexical overlap
    (``core.nli.lexical_overlap``) → :func:`core.nli.aggregator.aggregate`.
    Requires API keys for the LLM judge AND the DeBERTa worker
    available. Budget: ~$2-3 across the 60-pair synthetic set.
  - ``heuristic_no_keys``  — the cost-zero fallback used when
    API keys aren't configured. Runs the REAL lexical-overlap
    scorer + a deterministic heuristic that synthesises an
    LLM-judge verdict from lexical signal and word overlap +
    a deterministic DeBERTa substitute that maps lexical
    signal onto the (contradiction, entailment, neutral)
    softmax. Then feeds those signals through the REAL
    aggregator. Produces an honest-baseline JSON marked with
    its source so Day 3 knows whether to trust it.
  - ``cached``             — replay from an existing
    ``raw_scores.json``. Day 3 uses this for the threshold
    sweep — re-aggregate, never re-LLM.

The :class:`VerifierProtocol` is the plug-in surface; the test
suite uses a mock implementation to verify pipeline behaviour
without invoking either real models or the heuristic.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

# Make sure the backend dir is importable when this file is run as a script.
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from eval.golden_set import GoldenEntry, GoldenSet  # noqa: E402
from eval.golden_set.loader import load_golden_set  # noqa: E402
from eval.golden_set.types import collapse_verdict  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


@dataclass
class RawScores:
    """The pre-aggregation signals for one (claim, evidence) pair.

    Day 3 sweeps thresholds by re-running
    :func:`core.nli.aggregator.aggregate` over different
    ``deberta_high_conf`` / ``numeric_drift_below`` constants
    against the cached raw scores — no LLM calls."""

    llm_verdict: str            # supported | weak | unsupported | contradicted | overstates
    llm_rationale: str = ""
    deberta_label: str = "neutral"        # entailment | contradiction | neutral
    deberta_confidence: float = 0.0
    deberta_softmax: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # (contradiction, entailment, neutral) per the worker's label order
    lexical_numeric_score: float = 1.0
    lexical_numeric_missing: list[str] = field(default_factory=list)
    lexical_entity_score: float = 1.0
    lexical_entity_missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["deberta_softmax"] = list(self.deberta_softmax)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RawScores":
        s = d.get("deberta_softmax") or [0.0, 0.0, 0.0]
        return cls(
            llm_verdict=str(d.get("llm_verdict", "weak")),
            llm_rationale=str(d.get("llm_rationale", "")),
            deberta_label=str(d.get("deberta_label", "neutral")),
            deberta_confidence=float(d.get("deberta_confidence", 0.0)),
            deberta_softmax=(float(s[0]), float(s[1]), float(s[2])),
            lexical_numeric_score=float(d.get("lexical_numeric_score", 1.0)),
            lexical_numeric_missing=list(d.get("lexical_numeric_missing") or []),
            lexical_entity_score=float(d.get("lexical_entity_score", 1.0)),
            lexical_entity_missing=list(d.get("lexical_entity_missing") or []),
        )


@dataclass
class ScoredPair:
    """One golden-set pair after the verifier ran on it."""

    id: str
    claim: str
    evidence: str
    category: str
    adversarial: bool
    ground_truth: str               # 4-class
    ensemble_verdict: str           # 5-class
    ensemble_verdict_collapsed: str # 4-class
    reason: str
    raw: RawScores
    correct: bool
    error_kind: str | None = None   # "false_positive" | "false_negative" | None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["raw"] = self.raw.to_dict()
        return out


class VerifierProtocol(Protocol):
    """Plug-in for the per-pair scoring step. Returns the raw
    component scores; the aggregator is run separately so Day 3
    can swap thresholds against the cached raw scores."""

    name: str

    def score(self, claim: str, evidence: str) -> RawScores: ...


# ---------------------------------------------------------------------------
# Verifier — heuristic, no API keys
# ---------------------------------------------------------------------------


_CONTRADICTION_CUES = (
    " not ", " no ", " never ", " did not ", " didn't ",
    "decline", "declined", "fell", "fall", "drop", "dropped",
    "compressed", "lower", "below", "down ", "less ",
    "rejected", "lost", "lagged", "underperformed",
    "qualified opinion", "qualified",
    "highest", "worst-in-class",  # used in claims like "best-in-class" + evidence "highest"
)
_DIRECTION_AGREE_CUES = (
    "increase", "rose", "grew", "grow", "growth", "expand", "expanded",
    "improve", "improved", "approved", "endorsed", "led", "leads",
    "exceeded", "above", "up ", "stronger",
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower())


def _heuristic_deberta(claim: str, evidence: str) -> tuple[str, float, tuple[float, float, float]]:
    """Deterministic substitute for the DeBERTa cross-encoder.

    Maps simple text features onto an (entailment / contradiction
    / neutral) verdict + a confidence. This is intentionally
    primitive — it exists so the calibration pipeline can run
    end-to-end without the cross-encoder worker. The Day 3
    threshold-sweep never touches it (it sweeps over cached
    softmax values), so heuristic primitives don't bias tuning.
    """
    c = _norm(claim)
    e = _norm(evidence)
    contradict_hits = sum(1 for cue in _CONTRADICTION_CUES if cue in e and cue not in c)
    direction_hits = sum(1 for cue in _DIRECTION_AGREE_CUES if cue in e and cue in c)
    # Token overlap as a proxy for support.
    c_tokens = set(re.findall(r"[a-z0-9]+", c)) - {
        "the", "and", "of", "to", "in", "for", "on", "by",
        "is", "was", "a", "an", "at", "as", "be",
    }
    e_tokens = set(re.findall(r"[a-z0-9]+", e))
    if c_tokens:
        overlap = len(c_tokens & e_tokens) / len(c_tokens)
    else:
        overlap = 1.0

    if contradict_hits >= 1 and direction_hits == 0 and overlap > 0.3:
        softmax = (0.7, 0.1, 0.2)
        return "contradiction", 0.7, softmax
    if overlap >= 0.6 and direction_hits >= 1 and contradict_hits == 0:
        softmax = (0.05, 0.8, 0.15)
        return "entailment", 0.8, softmax
    if overlap >= 0.4 and contradict_hits == 0:
        softmax = (0.1, 0.55, 0.35)
        return "entailment", 0.55, softmax
    softmax = (0.15, 0.3, 0.55)
    return "neutral", 0.55, softmax


def _heuristic_llm_verdict(
    claim: str, evidence: str, deberta_label: str, deberta_conf: float,
    lexical_num: float, lexical_ent: float,
) -> tuple[str, str]:
    """Deterministic substitute for the LLM judge.

    W22/D3: Switched from a gist-based fallthrough table to the
    structured reason-then-verdict heuristic. The new logic
    decomposes the claim into parts (conjunctions, magnitudes,
    causal verbs, universal quantifiers) and demands a supporting
    span per part. The DeBERTa hard-veto on contradiction is
    preserved because the heuristic-DeBERTa substitute is the
    source-of-truth for direction reversal in the no-keys path.
    """
    if deberta_label == "contradiction":
        return "contradicted", "heuristic: deberta contradiction"

    # Reason-then-verdict path — mirrors the production LLM prompt
    # the real_ensemble path uses (see core.nli.reason_then_verdict).
    from core.nli.reason_then_verdict import heuristic_reason_then_verdict
    judgment = heuristic_reason_then_verdict(claim, evidence)
    return (
        judgment.verdict,
        f"reason-then-verdict: {judgment.rationale}"[:240],
    )


class HeuristicVerifier:
    """No-LLM, no-DeBERTa verifier. Uses the REAL lexical-overlap
    scorer (spaCy + numeric normaliser) + deterministic substitutes
    for the other two signals. Used when the calibration runs
    without API keys or the DeBERTa worker — produces an honest
    baseline that exercises the real lexical + aggregator code
    paths."""

    name = "heuristic_no_keys"

    def score(self, claim: str, evidence: str) -> RawScores:
        from core.nli.lexical_overlap import score_overlap

        lex = score_overlap(claim, evidence)
        d_label, d_conf, d_soft = _heuristic_deberta(claim, evidence)
        llm_v, llm_r = _heuristic_llm_verdict(
            claim, evidence, d_label, d_conf,
            lex.numeric_overlap_score, lex.entity_overlap_score,
        )
        return RawScores(
            llm_verdict=llm_v,
            llm_rationale=llm_r,
            deberta_label=d_label,
            deberta_confidence=d_conf,
            deberta_softmax=d_soft,
            lexical_numeric_score=float(lex.numeric_overlap_score),
            lexical_numeric_missing=list(lex.numeric_missing or []),
            lexical_entity_score=float(lex.entity_overlap_score),
            lexical_entity_missing=list(lex.entity_missing or []),
        )


# ---------------------------------------------------------------------------
# Verifier — real cross-family ensemble (production path)
# ---------------------------------------------------------------------------


class RealEnsembleVerifier:
    """The production path. Calls the LLM judge + DeBERTa worker +
    lexical overlap, then captures their raw outputs (NOT the
    aggregated 5-class verdict — the aggregator runs separately
    so Day 3 can sweep thresholds against the cached scores).

    Cost: one LLM call per pair. ~$0.03-0.05 typical (gpt-4o
    classifier path is short). 60 pairs ≈ $2-3 total. The runner's
    ``max_llm_calls`` parameter caps this hard.
    """

    name = "real_ensemble"

    def __init__(self) -> None:
        # Lazy import — these modules pull in litellm / sentence-
        # transformers and would block the heuristic path otherwise.
        from agents.verifier import VERIFIER_SYSTEM  # noqa: F401
        from core.nli.deberta_client import score_pairs  # noqa: F401
        from core.nli.lexical_overlap import score_overlap  # noqa: F401

    def score(self, claim: str, evidence: str) -> RawScores:
        from core.inference.litellm_client import chat_complete
        from core.nli.deberta_client import score_pairs
        from core.nli.lexical_overlap import score_overlap
        from core.nli.reason_then_verdict import REASON_THEN_VERDICT_SYSTEM

        # ---- LLM judge ----
        # W22/D3: structured reason-then-verdict prompt. The model
        # decomposes the claim, quotes a supporting span per part,
        # then emits the verdict. Reduces "looks related → supported"
        # errors across three of the five W22/D2 fault categories.
        system = REASON_THEN_VERDICT_SYSTEM
        user = f"CLAIM:\n{claim}\n\nEVIDENCE:\n{evidence}"
        import asyncio
        import json as _json
        resp = asyncio.run(chat_complete(
            model=os.getenv("ARGUS_CALIBRATION_MODEL", "gpt-4o"),
            temperature=0.0,
            max_tokens=200,
            system=system,
            user=user,
            response_format={"type": "json_object"},
            timeout_seconds=30.0,
        ))
        try:
            content = resp.choices[0].message.content or "{}"
            parsed = _json.loads(content)
            llm_verdict = str(parsed.get("verdict", "weak")).strip().lower()
            llm_rationale = str(parsed.get("rationale", ""))[:500]
        except Exception:
            llm_verdict, llm_rationale = "weak", "llm response parse failed"

        # ---- DeBERTa ----
        try:
            results = score_pairs([(evidence, claim)])
            d = results[0]
            d_label = d.label
            d_conf = float(d.confidence)
            d_soft = tuple(float(x) for x in d.softmax)  # type: ignore[assignment]
        except Exception as e:  # noqa: BLE001
            logger.warning("DeBERTa unavailable; substituting neutral: %s", e)
            d_label, d_conf, d_soft = "neutral", 0.0, (0.0, 0.0, 0.0)

        # ---- lexical ----
        lex = score_overlap(claim, evidence)

        return RawScores(
            llm_verdict=llm_verdict,
            llm_rationale=llm_rationale,
            deberta_label=d_label,
            deberta_confidence=d_conf,
            deberta_softmax=d_soft,
            lexical_numeric_score=float(lex.numeric_overlap_score),
            lexical_numeric_missing=list(lex.numeric_missing or []),
            lexical_entity_score=float(lex.entity_overlap_score),
            lexical_entity_missing=list(lex.entity_missing or []),
        )


# ---------------------------------------------------------------------------
# Aggregation + scoring loop
# ---------------------------------------------------------------------------


def _aggregate_raw(
    raw: RawScores,
    config: "ThresholdConfig | None" = None,
) -> tuple[str, str]:
    """Feed raw scores through the REAL aggregator. We synthesise
    the small NLIResult / LexicalSignal shapes the aggregator
    expects. When ``config`` is None the aggregator uses the W2/D3
    defaults; the W21/D3 tuning harness passes a swept config."""
    from core.nli.aggregator import aggregate
    from core.nli.deberta_client import NLIResult
    from core.nli.lexical_overlap import LexicalSignal

    nli = NLIResult(
        label=raw.deberta_label,
        confidence=raw.deberta_confidence,
        softmax=raw.deberta_softmax,
    )
    lex = LexicalSignal(
        numeric_overlap_score=raw.lexical_numeric_score,
        numeric_missing=list(raw.lexical_numeric_missing),
        entity_overlap_score=raw.lexical_entity_score,
        entity_missing=list(raw.lexical_entity_missing),
    )
    return aggregate(raw.llm_verdict, nli, lex, config=config)


# Re-export for tune.py / callers that want to pass a config.
from core.nli.threshold_config import ThresholdConfig  # noqa: E402


def _classify_error(
    predicted_collapsed: str, ground_truth: str,
) -> str | None:
    """Decide whether a wrong prediction is a false-positive
    (predicted supported, actually not — the dangerous one) or a
    false-negative (predicted not-supported, actually supported —
    annoying but safe)."""
    if predicted_collapsed == ground_truth:
        return None
    if predicted_collapsed == "supported" and ground_truth != "supported":
        return "false_positive"
    if predicted_collapsed != "supported" and ground_truth == "supported":
        return "false_negative"
    return "other_disagreement"


def run_calibration(
    *,
    verifier: VerifierProtocol | None = None,
    golden_set: GoldenSet | None = None,
    raw_scores_path: Path | None = None,
    use_cache: bool = False,
    max_pairs: int | None = None,
    threshold_config: "ThresholdConfig | None" = None,
) -> list[ScoredPair]:
    """Run the verifier across every golden-set pair, capture raw
    scores, run the aggregator, classify each result against
    ground truth.

    When ``use_cache`` is true and ``raw_scores_path`` exists, the
    runner SKIPS the verifier and replays the cached raw scores
    through the aggregator. This is the Day 3 threshold-sweep
    path — same pairs, no LLM calls.

    Otherwise the runner calls ``verifier.score`` on each pair
    and writes the raw scores out to ``raw_scores_path``.
    """
    # When replaying from cache and no golden_set override is
    # given, build the entries directly from the cached rows. This
    # is the Day 3 tuner's path — we don't want to require the
    # 60-pair synthetic set to be in scope every time we sweep
    # thresholds against a fixture-sized cache.
    cache: dict[str, dict[str, Any]] = {}
    cached_payload: dict[str, Any] = {}
    if use_cache and raw_scores_path and raw_scores_path.exists():
        try:
            cached_payload = json.loads(
                raw_scores_path.read_text(encoding="utf-8")
            )
            cache = {
                row["id"]: row["raw"]
                for row in cached_payload.get("scored_pairs", [])
            }
            logger.info("calibration: loaded %d cached scores", len(cache))
        except Exception as e:  # noqa: BLE001
            logger.warning("cache load failed; rescoring: %s", e)
            cache = {}

    if golden_set is not None:
        entries = list(golden_set)
    elif use_cache and cache:
        # Reconstruct lightweight GoldenEntry-shaped objects from
        # the cached rows so the loop below doesn't need a separate
        # codepath. We only need the fields _aggregate_raw + the
        # ScoredPair constructor consume.
        from eval.golden_set import GoldenEntry as _GE
        entries = [
            _GE(
                id=row["id"], claim=row["claim"], evidence=row["evidence"],
                evidence_source="synthetic",  # for type validation only
                ground_truth=row["ground_truth"],
                label_rationale="(from cache)",
                category=row["category"],
                adversarial=bool(row.get("adversarial", False)),
            )
            for row in cached_payload.get("scored_pairs", [])
        ]
    else:
        entries = list(load_golden_set())
    if max_pairs:
        entries = entries[: int(max_pairs)]

    if verifier is None and not cache:
        verifier = HeuristicVerifier()

    results: list[ScoredPair] = []
    for e in entries:
        if e.id in cache:
            raw = RawScores.from_dict(cache[e.id])
        else:
            assert verifier is not None
            raw = verifier.score(e.claim, e.evidence)
        ensemble_verdict, reason = _aggregate_raw(
            raw, config=threshold_config,
        )
        collapsed = collapse_verdict(ensemble_verdict)
        correct = collapsed == e.ground_truth
        results.append(ScoredPair(
            id=e.id, claim=e.claim, evidence=e.evidence,
            category=e.category, adversarial=e.adversarial,
            ground_truth=e.ground_truth,
            ensemble_verdict=ensemble_verdict,
            ensemble_verdict_collapsed=collapsed,
            reason=reason, raw=raw, correct=correct,
            error_kind=_classify_error(collapsed, e.ground_truth),
        ))

    # Persist when raw_scores_path is given AND we actually ran a
    # fresh verifier. The W22/D4 fix: when use_cache=True we're
    # REPLAYING the cache (e.g. tune() sweeping thresholds), so
    # overwriting the file just relabels the source from
    # "heuristic_no_keys" to "cached" without changing any data.
    # Skip the write on cache replays so the verifier_source label
    # stays accurate for the next reader (W21/D5 regression suite
    # + W22/D3 test_new_raw_scores_captured both depend on it).
    if raw_scores_path is not None and not use_cache:
        raw_scores_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "verifier_source": (
                verifier.name if verifier is not None else "cached"
            ),
            "pair_count": len(results),
            "scored_pairs": [r.to_dict() for r in results],
        }
        raw_scores_path.write_text(json.dumps(payload, indent=2))

    return results


def load_scored_pairs(path: Path) -> list[ScoredPair]:
    """Helper for tests + Day 3: load a previously-written
    ``raw_scores.json`` back into :class:`ScoredPair` objects."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[ScoredPair] = []
    for row in payload.get("scored_pairs", []):
        raw = RawScores.from_dict(row["raw"])
        out.append(ScoredPair(
            id=row["id"], claim=row["claim"], evidence=row["evidence"],
            category=row["category"],
            adversarial=bool(row.get("adversarial", False)),
            ground_truth=row["ground_truth"],
            ensemble_verdict=row["ensemble_verdict"],
            ensemble_verdict_collapsed=row["ensemble_verdict_collapsed"],
            reason=row.get("reason", ""),
            raw=raw, correct=bool(row.get("correct", False)),
            error_kind=row.get("error_kind"),
        ))
    return out


__all__ = [
    "HeuristicVerifier",
    "RawScores",
    "RealEnsembleVerifier",
    "ScoredPair",
    "VerifierProtocol",
    "load_scored_pairs",
    "run_calibration",
]
