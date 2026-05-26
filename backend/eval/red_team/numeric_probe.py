"""Numeric-consistency probe — Phase 5 / Week 21 / Day 4.

NLI cross-encoders + LLM judges are weak at arithmetic. They
anchor on gist + topic. So a claim that says "EBITDA grew 25%"
when the evidence says "EBITDA grew 15%" can land as
"supported" — the words look right, only the magnitude is off.
This is the most dangerous + most common hallucination class in
a financial deliverable.

The probe is a **post-aggregator hard veto**, NOT a relaxation
of "supported." It runs only against claims the ensemble has
already marked supported_high or supported_low; if the claim
contains any numeric value that doesn't appear in the evidence
(under the existing :mod:`core.nli.numeric_normalizer` matching),
the verdict is forcibly downgraded to ``weak`` with a reason
that flags the missing figure.

Hard-rule compliance: never weakens the definition of supported;
never overrides a contradicted/unsupported verdict. The probe
only ever downgrades supported_*. It is loud — the reason string
names the figure that triggered the veto.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from core.nli.lexical_overlap import score_overlap


@dataclass
class NumericProbeResult:
    """Output of the probe."""

    triggered: bool
    final_verdict: str          # the verdict AFTER the probe runs
    reason: str
    missing_numbers: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


_SUPPORTED_VERDICTS = {"supported_high", "supported_low"}


def numeric_consistency_check(
    ensemble_verdict: str, claim: str, evidence: str,
) -> NumericProbeResult:
    """Probe the (claim, evidence) pair for numeric drift on a
    would-be supported verdict.

    Returns a :class:`NumericProbeResult` carrying the FINAL
    verdict — equal to ``ensemble_verdict`` when the probe didn't
    fire, downgraded to ``"weak"`` when it did.

    The probe reuses :func:`core.nli.lexical_overlap.score_overlap`
    (which already implements numeric normalisation + matching) so
    we don't reinvent the regex / unit handling. Anything below
    ``score == 1.0`` on the claim's numerics means at least one
    claim number doesn't have a matching counterpart in the chunk.
    """
    if (ensemble_verdict or "").strip().lower() not in _SUPPORTED_VERDICTS:
        # Not a "supported" verdict — leave untouched.
        return NumericProbeResult(
            triggered=False,
            final_verdict=ensemble_verdict,
            reason="probe skipped: not a supported verdict",
            missing_numbers=[],
        )

    signal = score_overlap(claim or "", evidence or "")
    missing = list(signal.numeric_missing or [])
    if signal.numeric_overlap_score >= 1.0:
        # Claim has no numerics, or every claim numeric matched
        # something in the chunk. No drift.
        return NumericProbeResult(
            triggered=False,
            final_verdict=ensemble_verdict,
            reason=(
                "probe clean: numeric overlap "
                f"{signal.numeric_overlap_score:.2f}"
            ),
            missing_numbers=[],
        )

    # At least one claim number is absent from the chunk under
    # numeric normalisation. Veto the supported verdict.
    head = missing[:3]
    tail = ", ..." if len(missing) > 3 else ""
    reason = (
        "numeric consistency veto: claim numbers absent from evidence "
        f"({', '.join(head)}{tail})"
    )
    return NumericProbeResult(
        triggered=True,
        final_verdict="weak",
        reason=reason,
        missing_numbers=missing,
    )


__all__ = ["NumericProbeResult", "numeric_consistency_check"]
