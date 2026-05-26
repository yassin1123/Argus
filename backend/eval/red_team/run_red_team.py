"""Red-team runner — Phase 5 / Week 21 / Day 4.

Runs every adversarial pair from :mod:`adversarial_cases`
through the tuned verifier path + the numeric-consistency probe,
counts the catches + escapes, breaks them down by exploit type,
and writes a triage report to
``backend/eval_runs/week21_red_team/escapes.json``.

Catch rate = correctly-flagged-as-not-supported / total.
Escapes = pairs the verifier called supported despite the ground
truth being non-supported. **Every escape is a real
vulnerability** — the script lists them with their exploit type
so Day 5 wrap-up triage can decide fix-now vs document-as-
known-limitation.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.nli.threshold_config import (
    ThresholdConfig,
    load_threshold_config,
)
from eval.calibration.runner import (
    HeuristicVerifier,
    RawScores,
    VerifierProtocol,
    _aggregate_raw,
)
from eval.golden_set.types import collapse_verdict

from .adversarial_cases import (
    AdversarialCase,
    ExploitType,
    build_adversarial_cases,
)
from .numeric_probe import (
    NumericProbeResult,
    numeric_consistency_check,
)

logger = logging.getLogger(__name__)


_BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_OUT = (
    _BACKEND / "eval_runs" / "week21_red_team" / "escapes.json"
)


# ---------------------------------------------------------------------------
# Per-pair result
# ---------------------------------------------------------------------------


@dataclass
class RedTeamResult:
    """One adversarial pair after the verifier + probe ran."""

    id: str
    exploit_type: str
    claim: str
    evidence: str
    expected_verdict: str
    rationale: str
    pre_probe_verdict: str           # 5-class ensemble verdict
    pre_probe_collapsed: str         # 4-class
    final_verdict: str               # after numeric probe
    final_collapsed: str             # 4-class after probe
    probe_triggered: bool
    probe_reason: str
    caught: bool                     # True iff final_collapsed != "supported"
    escape: bool                     # True iff verifier ended supported
    raw: RawScores

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["raw"] = self.raw.to_dict()
        return d


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _score_case(
    case: AdversarialCase,
    verifier: VerifierProtocol,
    config: ThresholdConfig,
    apply_numeric_probe: bool,
) -> RedTeamResult:
    raw = verifier.score(case.claim, case.evidence)
    pre_verdict, _pre_reason = _aggregate_raw(raw, config=config)
    pre_collapsed = collapse_verdict(pre_verdict)

    probe_triggered = False
    probe_reason = "probe disabled"
    final_verdict = pre_verdict
    if apply_numeric_probe:
        probe = numeric_consistency_check(
            pre_verdict, case.claim, case.evidence,
        )
        probe_triggered = probe.triggered
        probe_reason = probe.reason
        final_verdict = probe.final_verdict
    final_collapsed = collapse_verdict(final_verdict)

    caught = final_collapsed != "supported"
    escape = not caught
    return RedTeamResult(
        id=case.id, exploit_type=case.exploit_type,
        claim=case.claim, evidence=case.evidence,
        expected_verdict=case.expected_verdict,
        rationale=case.rationale,
        pre_probe_verdict=pre_verdict,
        pre_probe_collapsed=pre_collapsed,
        final_verdict=final_verdict,
        final_collapsed=final_collapsed,
        probe_triggered=probe_triggered,
        probe_reason=probe_reason,
        caught=caught,
        escape=escape,
        raw=raw,
    )


def run_red_team(
    *,
    verifier: VerifierProtocol | None = None,
    config: ThresholdConfig | None = None,
    cases: list[AdversarialCase] | None = None,
    apply_numeric_probe: bool = True,
) -> list[RedTeamResult]:
    """Score every adversarial case under the tuned ensemble +
    (optionally) the numeric-consistency probe. Returns one row
    per case."""
    v = verifier if verifier is not None else HeuristicVerifier()
    cfg = config if config is not None else load_threshold_config()
    pairs = cases if cases is not None else build_adversarial_cases()
    return [
        _score_case(c, v, cfg, apply_numeric_probe) for c in pairs
    ]


# ---------------------------------------------------------------------------
# Triage + report
# ---------------------------------------------------------------------------


def _per_exploit_breakdown(
    results: list[RedTeamResult],
) -> dict[str, dict[str, Any]]:
    """For each exploit type: total, caught, escapes, catch_rate."""
    by_type: dict[str, dict[str, Any]] = {
        t.value: {"total": 0, "caught": 0, "escapes": [], "catch_rate": 0.0}
        for t in ExploitType
    }
    for r in results:
        bucket = by_type[r.exploit_type]
        bucket["total"] += 1
        if r.caught:
            bucket["caught"] += 1
        else:
            bucket["escapes"].append(r.id)
    for bucket in by_type.values():
        bucket["catch_rate"] = (
            bucket["caught"] / bucket["total"] if bucket["total"] else 0.0
        )
    return by_type


# Mitigation library — for each exploit type, the prescribed fix
# when an escape lands. This lives in code (not free text) so the
# triage report carries a stable mitigation column per row.
EXPLOIT_MITIGATIONS: dict[str, str] = {
    ExploitType.MAGNITUDE_MISMATCH.value: (
        "Numeric-consistency probe (W21/D4 numeric_probe) — vetoes "
        "supported when claim numbers don't match the chunk. If the "
        "probe still misses, the claim's numeric phrasing isn't being "
        "captured by the normaliser; add to numeric_normalizer test set."
    ),
    ExploitType.MISATTRIBUTION.value: (
        "Out-of-scope for threshold tuning — the LLM judge needs to "
        "attend to speaker / source attribution. Documented limitation; "
        "Week 22 prompt-tightening + an entity-attribution check would "
        "close it. NOT a threshold problem."
    ),
    ExploitType.TEMPORAL_DRIFT.value: (
        "Out-of-scope for thresholds. The numeric probe catches a subset "
        "(when the year itself is a missing numeric). Full fix needs a "
        "temporal-entity attention check in the LLM prompt + a "
        "claim-period vs chunk-period matcher. Known limitation."
    ),
    ExploitType.OVERCLAIM.value: (
        "Borderline-band downgrade (W21/D3 conservative default) helps "
        "when LLM hedges in its reasoning. Full fix: a hedge-aware LLM "
        "judge prompt asking 'does the evidence support the STRENGTH "
        "of the claim, not just the topic?' Documented; addressable."
    ),
    ExploitType.FABRICATED_SPECIFIC.value: (
        "Numeric-consistency probe is the primary catch for fabricated "
        "numbers. For fabricated non-numeric specifics, the LLM judge "
        "is the only signal — known limitation."
    ),
    ExploitType.PLAUSIBLE_BUT_ABSENT.value: (
        "LLM-judge prompt addition: 'is the specific assertion in the "
        "chunk, or only adjacent?' Documented limitation; not "
        "threshold-fixable."
    ),
    ExploitType.NEGATION_FLIP.value: (
        "Known weakness of NLI cross-encoders. DeBERTa-v3 picks up "
        "explicit negation but misses subtle 'considered but did not'. "
        "Known limitation; mitigation is an explicit negation-detection "
        "preprocessor on the chunk side."
    ),
    ExploitType.CHERRY_PICK.value: (
        "Out-of-scope for verifier. The LLM judge would need quantitative "
        "reasoning over the chunk to detect 'true of one of N, generalised "
        "to all of N'. Known limitation; pyramid-coherence check in "
        "critic agent is the existing partial mitigation."
    ),
}


def triage(results: list[RedTeamResult]) -> dict[str, Any]:
    """Walk the results, group escapes by exploit type, attach
    mitigations. Returns the dict that lands in escapes.json."""
    by_type = _per_exploit_breakdown(results)
    escapes: list[dict[str, Any]] = []
    for r in results:
        if r.escape:
            escapes.append({
                "id": r.id,
                "exploit_type": r.exploit_type,
                "claim_head": (r.claim or "")[:140],
                "evidence_head": (r.evidence or "")[:140],
                "expected_verdict": r.expected_verdict,
                "pre_probe_verdict": r.pre_probe_verdict,
                "final_verdict": r.final_verdict,
                "probe_triggered": r.probe_triggered,
                "probe_reason": r.probe_reason,
                "raw_llm_verdict": r.raw.llm_verdict,
                "raw_deberta_label": r.raw.deberta_label,
                "raw_deberta_confidence": round(r.raw.deberta_confidence, 3),
                "raw_lexical_numeric_score": round(
                    r.raw.lexical_numeric_score, 3,
                ),
                "rationale": r.rationale,
                "prescribed_mitigation": EXPLOIT_MITIGATIONS.get(
                    r.exploit_type, "(none on file)",
                ),
            })
    total = len(results)
    caught = sum(1 for r in results if r.caught)
    return {
        "total": total,
        "caught": caught,
        "escapes": len(escapes),
        "catch_rate": (caught / total) if total else 0.0,
        "per_exploit_type": by_type,
        "escape_details": escapes,
    }


def write_red_team_report(
    *,
    out_path: Path | None = None,
    apply_numeric_probe: bool = True,
    verifier: VerifierProtocol | None = None,
    config: ThresholdConfig | None = None,
) -> dict[str, Any]:
    results = run_red_team(
        verifier=verifier, config=config,
        apply_numeric_probe=apply_numeric_probe,
    )
    summary = triage(results)
    # Also run with probe DISABLED for the report so the operator
    # sees the probe's contribution.
    if apply_numeric_probe:
        no_probe_results = run_red_team(
            verifier=verifier, config=config,
            apply_numeric_probe=False,
        )
        summary["probe_contribution"] = {
            "catch_rate_with_probe": summary["catch_rate"],
            "catch_rate_without_probe": (
                sum(1 for r in no_probe_results if r.caught)
                / max(1, len(no_probe_results))
            ),
            "additional_catches_from_probe": sum(
                1 for w, wo in zip(results, no_probe_results)
                if w.caught and not wo.caught
            ),
        }

    report = {
        "config_used": (
            config.to_dict() if config else load_threshold_config().to_dict()
        ),
        "numeric_probe_enabled": apply_numeric_probe,
        "summary": summary,
        "all_results": [r.to_dict() for r in results],
    }
    out = out_path or DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument(
        "--no-numeric-probe", action="store_true",
        help="Disable the numeric-consistency probe (for A/B reporting).",
    )
    args = ap.parse_args(argv)

    report = write_red_team_report(
        out_path=Path(args.out),
        apply_numeric_probe=not args.no_numeric_probe,
    )
    s = report["summary"]
    print()
    print("=== W21/D4 hallucination red-team ===")
    print(f"  cases: {s['total']}   caught: {s['caught']}   "
          f"escapes: {s['escapes']}   catch_rate: {s['catch_rate']:.1%}")
    if "probe_contribution" in s:
        pc = s["probe_contribution"]
        print()
        print(f"  numeric-probe contribution:")
        print(f"    without probe: {pc['catch_rate_without_probe']:.1%}")
        print(f"    with probe:    {pc['catch_rate_with_probe']:.1%}  "
              f"(+{pc['additional_catches_from_probe']} catches)")

    print()
    print("  per exploit type:")
    for exploit, bucket in s["per_exploit_type"].items():
        print(f"    {exploit:24s} {bucket['caught']}/{bucket['total']:<3} "
              f"({bucket['catch_rate']:.0%})")

    print()
    if s["escape_details"]:
        print("  escapes (real vulnerabilities):")
        for e in s["escape_details"]:
            print(f"    {e['id']} [{e['exploit_type']}]")
            print(f"      claim:  {e['claim_head'][:100]}")
            print(f"      final:  {e['final_verdict']}")
            print(f"      mitig:  {e['prescribed_mitigation'][:96]}")
    else:
        print("  no escapes -- every adversarial case was flagged.")
    print()
    print(f"  report -> {args.out}")
    return 0


__all__ = [
    "EXPLOIT_MITIGATIONS",
    "RedTeamResult",
    "run_red_team",
    "triage",
    "write_red_team_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
