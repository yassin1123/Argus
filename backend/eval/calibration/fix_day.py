"""W22 Fix-Day calibration runner — Phase 5 / Week 22 / Fix-Day.

Closes the two calibration gaps that made the W22 numbers
unusable as a pilot trust claim:

  1. Zero real claims were labelled — true production FP rate
     unknown.
  2. Calibration ran on the heuristic_no_keys fallback verifier,
     not the real cross-family LLM ensemble.

Hard pre-flight checks (the gate):

  - API keys MUST be present (ANTHROPIC + OPENAI). If absent,
    the runner refuses to proceed and writes a clear
    ``gate_blocked`` verdict.
  - The verifier source is recorded precisely. With real LLM
    available but DeBERTa absent, the label is
    ``real_llm_no_deberta`` — NEVER ``cross_family_llm`` (that
    name is reserved for the full three-signal ensemble).

The runner produces:

  - Cached raw scores at ``backend/eval/calibration/raw_scores_w22fix.json``
  - Verdict at ``backend/eval_runs/week22_fix/verdict.json``
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv

# Load .env BEFORE importing anything that touches the LLM clients
# so the project's normal key-discovery path is used (matches main.py).
_REPO_ROOT = _BACKEND.parent
load_dotenv(_REPO_ROOT / ".env")

from eval.calibration.metrics import compute_metrics, split_failures  # noqa: E402
from eval.calibration.recalibrate import (  # noqa: E402
    HUMAN_REVIEW_FP_CEILING,
    READY_FP_CEILING,
    W21_BASELINE,
    classify_pilot_readiness,
)
from eval.calibration.runner import (  # noqa: E402
    RealEnsembleVerifier,
    RawScores,
    ScoredPair,
    run_calibration,
)
from eval.calibration.tune import assess_over_flagging  # noqa: E402
from eval.golden_set.loader import load_golden_set, load_real_run_entries  # noqa: E402

logger = logging.getLogger(__name__)


OUT_DIR = _BACKEND / "eval_runs" / "week22_fix"
VERDICT_PATH = OUT_DIR / "verdict.json"
RAW_SYNTH = _BACKEND / "eval" / "calibration" / "raw_scores_w22fix.json"
RAW_REAL = _BACKEND / "eval" / "calibration" / "raw_scores_w22fix_real.json"


# ---------------------------------------------------------------------------
# Gate-keeping pre-flight
# ---------------------------------------------------------------------------


@dataclass
class GateCheck:
    """The hard pre-flight result. ``blocked=True`` means the
    fix-day cannot proceed — we write a verdict that surfaces
    exactly which key/dependency is missing rather than running
    a degraded calibration and reporting it as real."""

    blocked: bool
    blockers: list[str] = field(default_factory=list)
    available: dict[str, bool] = field(default_factory=dict)
    chosen_verifier_source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_gate() -> GateCheck:
    """Inspect API keys + DeBERTa availability. Decides whether
    the runner can produce a real-verifier number or must fail
    loudly."""
    available: dict[str, bool] = {}
    blockers: list[str] = []

    anth = os.getenv("ANTHROPIC_API_KEY") or ""
    oai = os.getenv("OPENAI_API_KEY") or ""
    available["anthropic_key"] = bool(anth) and len(anth) > 16
    available["openai_key"] = bool(oai) and len(oai) > 16
    if not available["anthropic_key"]:
        blockers.append(
            "ANTHROPIC_API_KEY missing — load_dotenv() saw no key. "
            "Set it in .env or the process env before re-running."
        )
    if not available["openai_key"]:
        blockers.append(
            "OPENAI_API_KEY missing — load_dotenv() saw no key. "
            "Set it in .env or the process env before re-running."
        )

    # DeBERTa is the third ensemble signal. Its absence is a
    # softer blocker — we can still produce a real-LLM number,
    # but we label the source precisely.
    try:
        import sentence_transformers  # noqa: F401
        available["deberta_module"] = True
    except ImportError:
        available["deberta_module"] = False

    if not (available["anthropic_key"] and available["openai_key"]):
        chosen = "blocked"
        return GateCheck(
            blocked=True, blockers=blockers,
            available=available,
            chosen_verifier_source=chosen,
        )

    if available["deberta_module"]:
        chosen = "cross_family_llm"
    else:
        chosen = "real_llm_no_deberta"
        blockers.append(
            "sentence_transformers not installed — DeBERTa cross-"
            "encoder will return neutral/0.0 (the production "
            "worker-timeout fallback). The LLM judge + lexical "
            "signals are real; the cross-encoder is degraded. "
            "Source labelled 'real_llm_no_deberta', NOT "
            "'cross_family_llm'."
        )

    return GateCheck(
        blocked=False, blockers=blockers,
        available=available,
        chosen_verifier_source=chosen,
    )


# ---------------------------------------------------------------------------
# Real-LLM verifier wrapping (light shim — uses RealEnsembleVerifier
# but tags the source string correctly when DeBERTa is degraded)
# ---------------------------------------------------------------------------


class RealLLMVerifier(RealEnsembleVerifier):
    """Same scoring code as :class:`RealEnsembleVerifier` (real
    LLM + DeBERTa + lexical, falling back to neutral when DeBERTa
    isn't reachable). The only override is ``name`` — set to the
    precise gate label so downstream artefacts never claim
    'cross_family_llm' when the cross-encoder is actually absent.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name  # "cross_family_llm" or "real_llm_no_deberta"


# ---------------------------------------------------------------------------
# Real-claim batch availability
# ---------------------------------------------------------------------------


@dataclass
class RealBatchStatus:
    """The state of the labelled-real-claims batch. The fix-day
    spec wants ≥40 labelled pairs; we record exactly what's
    available so the verdict can name the gap."""

    labelled_pair_count: int
    chunk_text_complete: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_real_batch() -> RealBatchStatus:
    """Walk ``backend/eval/golden_set/real_runs/`` for labelled
    fixtures. Also checks whether any entries are missing chunk
    text — a known W22/D1 gap where the committed eval_runs slim
    evidence to metadata only."""
    entries = load_real_run_entries()
    notes: list[str] = []
    chunk_text_complete = True
    for e in entries:
        if not (e.evidence or "").strip():
            chunk_text_complete = False
            break
    if len(entries) == 0:
        notes.append(
            "real_runs/ has no labelled fixtures. The labelling CLI "
            "(tools/label_claims.py) is ready; needs Yassin's 30-60 min."
        )
    elif len(entries) < 40:
        notes.append(
            f"Only {len(entries)} labelled real-claim pairs (spec "
            "minimum is 30, target 40). Add more before claiming a "
            "real-claim FP rate."
        )
    if entries and not chunk_text_complete:
        notes.append(
            "Some labelled entries have empty evidence text. The "
            "W22/D1 finding was that committed eval_runs slim "
            "evidence to metadata only — chunk text needs a DB "
            "lookup (or fresh extraction via --source db) to "
            "complete."
        )
    return RealBatchStatus(
        labelled_pair_count=len(entries),
        chunk_text_complete=chunk_text_complete,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# The fix-day runner
# ---------------------------------------------------------------------------


def run_synthetic_on_real_llm(
    gate: GateCheck, max_pairs: int | None = None,
) -> dict[str, Any]:
    """Run the W21/D1 60-pair synthetic golden set through the
    real LLM verifier. Returns the metrics dict + the raw cache
    location."""
    verifier = RealLLMVerifier(name=gate.chosen_verifier_source)
    gs = load_golden_set(
        include_synthetic=True, include_real_runs=False,
    )
    pairs = run_calibration(
        verifier=verifier,
        golden_set=gs,
        raw_scores_path=RAW_SYNTH,
        use_cache=False,
        max_pairs=max_pairs,
    )
    metrics = compute_metrics(pairs)
    over_flag = assess_over_flagging(metrics.to_dict())
    return {
        "verifier_source": verifier.name,
        "pair_count": len(pairs),
        "metrics_full": metrics.to_dict(),
        "headline": {
            "fp_rate_on_supported": metrics.fp_rate_on_supported,
            "recall_on_insufficient": metrics.recall_on_insufficient,
            "accuracy": metrics.accuracy,
            "adversarial_accuracy": metrics.adversarial_accuracy,
        },
        "over_flagging": over_flag,
        "raw_scores_path": str(RAW_SYNTH),
    }


def run_real_on_real_llm(
    gate: GateCheck, status: RealBatchStatus,
    max_pairs: int | None = None,
) -> dict[str, Any] | None:
    """Run the labelled real-claim batch through the real LLM
    verifier — only when there are actually labels to score
    against AND every row has chunk text. Returns ``None`` when
    the batch is empty or incomplete, with the verdict capturing
    the reason."""
    if status.labelled_pair_count == 0 or not status.chunk_text_complete:
        return None
    real = load_golden_set(
        include_synthetic=False, include_real_runs=True,
    )
    verifier = RealLLMVerifier(name=gate.chosen_verifier_source)
    pairs = run_calibration(
        verifier=verifier,
        golden_set=real,
        raw_scores_path=RAW_REAL,
        use_cache=False,
        max_pairs=max_pairs,
    )
    metrics = compute_metrics(pairs)
    over_flag = assess_over_flagging(metrics.to_dict())
    return {
        "verifier_source": verifier.name,
        "pair_count": len(pairs),
        "metrics_full": metrics.to_dict(),
        "headline": {
            "fp_rate_on_supported": metrics.fp_rate_on_supported,
            "recall_on_insufficient": metrics.recall_on_insufficient,
            "accuracy": metrics.accuracy,
        },
        "over_flagging": over_flag,
        "raw_scores_path": str(RAW_REAL),
    }


# ---------------------------------------------------------------------------
# Verdict assembly
# ---------------------------------------------------------------------------


def build_verdict(
    *,
    gate: GateCheck,
    real_batch: RealBatchStatus,
    synthetic_real_llm: dict[str, Any] | None,
    real_real_llm: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble the verdict.json that the spec asks for. Always
    writes — including in the gate-blocked path — so the blocker
    is surfaced, not hidden."""
    if gate.blocked:
        return {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "gate_status": "blocked",
            "gate_check": gate.to_dict(),
            "real_batch_status": real_batch.to_dict(),
            "synthetic_on_real_llm": None,
            "real_on_real_llm": None,
            "verdict": {
                "headline": "GATE_BLOCKED",
                "rationale": (
                    "API keys not present at run time. Fix-day "
                    "cannot proceed without the real cross-family "
                    "LLM ensemble. Every prior W21/W22 calibration "
                    "number remains a heuristic-mode measurement; "
                    "the pilot trust claim still rests on the "
                    "heuristic baseline until keys are provided "
                    "and this runner re-runs."
                ),
                "pilot_posture_action": "no_change_until_keys_present",
                "next_steps": [
                    "Set ANTHROPIC_API_KEY + OPENAI_API_KEY in .env "
                    "or the process env.",
                    "Re-run: python -m eval.calibration.fix_day",
                ],
            },
        }

    # Decide the headline verdict from the real-claim run if we
    # have it; otherwise fall back to the synthetic-on-real-LLM
    # run and explicitly say the real-claim number is unmeasured.
    if real_real_llm and real_real_llm["pair_count"] > 0:
        head = real_real_llm["headline"]
        over = real_real_llm["over_flagging"]
        posture = classify_pilot_readiness(
            fp_rate_post_fix=float(head["fp_rate_on_supported"]),
            over_flag_status=str(over["status"]),
            red_team_catch_rate=W21_BASELINE["red_team_catch_rate"],
        )
        verdict_headline = "GATE_CLOSED_FULL"
        rationale = (
            "Real-claim calibration ran on the real LLM verifier "
            f"({gate.chosen_verifier_source}). Real-claim FP-rate-on-"
            f"supported = {head['fp_rate_on_supported']:.2%}. Pilot "
            f"posture re-classified: {posture.verdict}."
        )
        posture_dict = posture.to_dict()
    elif synthetic_real_llm:
        head = synthetic_real_llm["headline"]
        over = synthetic_real_llm["over_flagging"]
        posture = classify_pilot_readiness(
            fp_rate_post_fix=float(head["fp_rate_on_supported"]),
            over_flag_status=str(over["status"]),
            red_team_catch_rate=W21_BASELINE["red_team_catch_rate"],
        )
        verdict_headline = "GATE_PARTIALLY_CLOSED"
        rationale = (
            "Synthetic calibration ran on the real LLM verifier "
            f"({gate.chosen_verifier_source}); real-claim "
            "calibration is STILL UNMEASURED because the labelled-"
            "real-claim batch is incomplete "
            f"({real_batch.labelled_pair_count} pairs; chunk text "
            f"complete={real_batch.chunk_text_complete}). The "
            "synthetic-on-real-LLM FP-rate-on-supported = "
            f"{head['fp_rate_on_supported']:.2%}. The pilot posture "
            "is re-classified against this synthetic-on-real-LLM "
            "number; the production-real-claim posture remains "
            "PENDING until the labels land."
        )
        posture_dict = posture.to_dict()
    else:
        verdict_headline = "GATE_BLOCKED_DEPENDENCIES"
        rationale = (
            "Neither real-claim nor synthetic calibration produced "
            "a real-LLM number this session. See gate_check + "
            "real_batch_status for the blockers."
        )
        posture_dict = None

    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "gate_status": "closed" if verdict_headline == "GATE_CLOSED_FULL"
                       else "partial" if verdict_headline == "GATE_PARTIALLY_CLOSED"
                       else "blocked_dependencies",
        "gate_check": gate.to_dict(),
        "real_batch_status": real_batch.to_dict(),
        "synthetic_on_real_llm": synthetic_real_llm,
        "real_on_real_llm": real_real_llm,
        "synthetic_heuristic_baseline_for_compare": {
            # W22/D3 frozen synthetic-on-heuristic numbers we
            # diff against.
            "fp_rate_on_supported": 0.4375,
            "recall_on_insufficient": 0.9333,
            "verifier_source": "heuristic_no_keys",
        },
        "delta_real_llm_vs_heuristic": _delta_block(
            synthetic_real_llm,
            heuristic_fp=0.4375,
            heuristic_recall=0.9333,
        ),
        "verdict": {
            "headline": verdict_headline,
            "rationale": rationale,
            "pilot_posture": posture_dict,
        },
    }


def _delta_block(
    synth: dict[str, Any] | None,
    *,
    heuristic_fp: float,
    heuristic_recall: float,
) -> dict[str, Any] | None:
    if not synth:
        return None
    head = synth["headline"]
    return {
        "fp_rate_real_llm": head["fp_rate_on_supported"],
        "fp_rate_heuristic": heuristic_fp,
        "fp_delta_pp": round(
            100 * (head["fp_rate_on_supported"] - heuristic_fp), 2,
        ),
        "recall_real_llm": head["recall_on_insufficient"],
        "recall_heuristic": heuristic_recall,
        "recall_delta_pp": round(
            100 * (head["recall_on_insufficient"] - heuristic_recall), 2,
        ),
    }


def write_verdict(verdict: dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    VERDICT_PATH.write_text(json.dumps(verdict, indent=2))
    return VERDICT_PATH


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--max-pairs", type=int, default=None,
        help="Cap pairs per set (smoke tests only).",
    )
    ap.add_argument(
        "--skip-synthetic", action="store_true",
        help="Skip the synthetic-on-real-LLM run (saves ~$2 if "
             "you only want the gate check + real-claim run).",
    )
    args = ap.parse_args(argv)

    print()
    print("=== W22 Fix-Day: real-claim calibration on the real verifier ===")
    print()

    gate = check_gate()
    print(f"  gate check:")
    for k, v in gate.available.items():
        print(f"    {k:24s} {'OK' if v else 'MISSING'}")
    print(f"  chosen verifier_source: {gate.chosen_verifier_source}")
    if gate.blockers:
        for b in gate.blockers:
            print(f"  WARN: {b}")

    real_batch = assess_real_batch()
    print()
    print(f"  real-claim batch:")
    print(f"    labelled pairs:        {real_batch.labelled_pair_count}")
    print(f"    chunk_text_complete:   {real_batch.chunk_text_complete}")
    for note in real_batch.notes:
        print(f"    note: {note}")

    if gate.blocked:
        verdict = build_verdict(
            gate=gate, real_batch=real_batch,
            synthetic_real_llm=None, real_real_llm=None,
        )
        write_verdict(verdict)
        print()
        print("  GATE BLOCKED — verdict written without running calibration.")
        print(f"  verdict -> {VERDICT_PATH}")
        return 1

    synthetic_real_llm: dict[str, Any] | None = None
    if not args.skip_synthetic:
        print()
        print("  running synthetic golden set through real LLM verifier...")
        synthetic_real_llm = run_synthetic_on_real_llm(
            gate, max_pairs=args.max_pairs,
        )
        h = synthetic_real_llm["headline"]
        print(f"    accuracy:               {h['accuracy']:.2%}")
        print(f"    FP-rate-on-supported:   {h['fp_rate_on_supported']:.2%}")
        print(f"    recall-on-insufficient: {h['recall_on_insufficient']:.2%}")
        of = synthetic_real_llm["over_flagging"]
        print(f"    over-flag status:       {of['status']} "
              f"({of['supported_review_fraction']:.0%})")

    real_real_llm: dict[str, Any] | None = None
    if real_batch.labelled_pair_count > 0 and real_batch.chunk_text_complete:
        print()
        print("  running labelled real-claim batch through real LLM verifier...")
        real_real_llm = run_real_on_real_llm(gate, real_batch)
        if real_real_llm:
            h = real_real_llm["headline"]
            print(f"    accuracy:               {h['accuracy']:.2%}")
            print(f"    FP-rate-on-supported:   {h['fp_rate_on_supported']:.2%}")
            print(f"    recall-on-insufficient: {h['recall_on_insufficient']:.2%}")
    else:
        print()
        print("  real-claim batch incomplete — skipping real-claim run.")

    verdict = build_verdict(
        gate=gate, real_batch=real_batch,
        synthetic_real_llm=synthetic_real_llm,
        real_real_llm=real_real_llm,
    )
    write_verdict(verdict)

    v = verdict["verdict"]
    print()
    print(f"  VERDICT: {v['headline']}")
    print(f"  {v['rationale']}")
    if v.get("pilot_posture"):
        print(f"  pilot posture: {v['pilot_posture']['verdict']}")
    print()
    print(f"  verdict -> {VERDICT_PATH}")
    return 0


__all__ = [
    "GateCheck",
    "RealBatchStatus",
    "RealLLMVerifier",
    "assess_real_batch",
    "build_verdict",
    "check_gate",
    "run_real_on_real_llm",
    "run_synthetic_on_real_llm",
    "write_verdict",
]


if __name__ == "__main__":
    raise SystemExit(main())
