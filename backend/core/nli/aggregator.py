"""Three-signal ensemble aggregator (Phase 1 / Week 2 / Day 3).

Pure function. Combines:
1. The LLM judge's verdict (existing path — produced by VerifierAgent).
2. The DeBERTa cross-encoder's NLI label + confidence (Day 1).
3. The lexical-overlap signal — numeric + entity precision (Day 2).

Into a single ``ensemble_verdict`` per (claim, chunk) pair plus a short
human-readable ``reason`` string for the UI / audit log.

KEY INVARIANT — the aggregator NEVER UPGRADES THE LLM VERDICT.
================================================================
If the LLM judge says "weak", the result is at most "weak". DeBERTa
saying "entailment" cannot rescue an LLM-weak verdict. The LLM has
context the other signals don't (the full chunk, the consulting mode,
the surrounding claims) and that context is load-bearing — when it
says "weak" we treat that as load-bearing too.

The aggregator only DOWNGRADES — moving "supported" to "weak" or
"contradicted" when DeBERTa or the lexical layer disagrees.

Truth table — see test_aggregator.py for one parametrized case per row.
The numbers are NOT to be tuned during Day 3; if they're wrong, Day 4's
ensemble regression run will tell us and Day 5 reconciles with evidence.
"""

from __future__ import annotations

from core.nli.deberta_client import NLIResult
from core.nli.lexical_overlap import LexicalSignal
from core.nli.threshold_config import (
    ThresholdConfig,
    default_threshold_config,
)

# ---------------------------------------------------------------------------
# Default tuning constants (W2/D3 baseline).
# ---------------------------------------------------------------------------
#
# Phase 5 / Week 21 / Day 3 moved these into
# :class:`ThresholdConfig` so the calibration harness can sweep
# them against the cached raw scores. The module-level constants
# below are retained as the documented default values; behaviour
# changes only when a tuned ``ThresholdConfig`` is passed in
# explicitly (e.g. by the orchestrator after
# :func:`load_threshold_config()` populates one from the YAML).

# DeBERTa entailment is only "high confidence" when the cross-encoder is
# fairly sure. Below this it's a soft signal that doesn't fully ratify the
# LLM's "supported" verdict.
_DEBERTA_HIGH_CONF: float = 0.7

# Numeric overlap below this threshold signals drift — the claim asserted
# numbers (currency, percent, date, count) the chunk doesn't support, even
# if the gist matches.
_NUMERIC_DRIFT_BELOW: float = 0.95


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_missing(missing: list[str]) -> str:
    return missing[0] if missing else ""


def _missing_join(missing: list[str], cap: int = 3) -> str:
    if not missing:
        return ""
    head = missing[:cap]
    suffix = ", …" if len(missing) > cap else ""
    return ", ".join(head) + suffix


# ---------------------------------------------------------------------------
# Main aggregator
# ---------------------------------------------------------------------------


def aggregate(
    llm_verdict: str,
    deberta: NLIResult,
    lexical: LexicalSignal,
    config: ThresholdConfig | None = None,
) -> tuple[str, str]:
    """Combine the three signals into ``(ensemble_verdict, reason)``.

    Parameters
    ----------
    llm_verdict:
        One of ``"supported"``, ``"weak"``, ``"unsupported"``,
        ``"overstates"``, ``"contradicted"``. Anything else is treated as
        ``"weak"`` (defensive — keeps the aggregator pure and total).
    deberta:
        ``NLIResult`` from ``core.nli.deberta_client.score_pairs``. May be
        a synthetic neutral-with-zero-confidence value if the DeBERTa
        worker timed out — ``nli_verifier`` substitutes that and the
        truth table treats it as "neutral, low confidence".
    lexical:
        ``LexicalSignal`` from ``core.nli.lexical_overlap.score_overlap``.
        When the claim has zero extractable numerics or entities the
        scorer returns ``score=1.0`` and empty ``missing`` — the
        aggregator transparently treats that as "no drift signal".

    Returns
    -------
    tuple[str, str]
        ``(ensemble_verdict, reason)``. Verdicts:

        - ``"supported_high"``  all three signals agree
        - ``"supported_low"``   LLM + structural pass, but one signal is
                                weak (DeBERTa low-conf or numeric drift)
        - ``"weak"``            LLM was weak, OR LLM said supported but
                                two/three signals disagree
        - ``"unsupported"``     LLM said unsupported (sticky)
        - ``"contradicted"``    LLM contradicted, OR LLM said supported
                                but DeBERTa says contradiction

        ``supported_high`` and ``supported_low`` both flow as
        "supported" through downstream gates today (writer / critic /
        contradiction policy do not differentiate; that's a future
        tightening). The split is preserved on the row so Day 4
        regression can analyse the two populations separately.
    """
    cfg = config or default_threshold_config()
    high_conf = float(cfg.deberta_high_conf)
    drift_below = float(cfg.numeric_drift_below)
    band = float(cfg.borderline_band)

    verdict = (llm_verdict or "").strip().lower()
    label = (deberta.label or "").strip().lower()
    conf = float(deberta.confidence or 0.0)
    num_score = float(lexical.numeric_overlap_score)
    num_missing = list(lexical.numeric_missing or [])

    # --- Sticky LLM verdicts: aggregator never upgrades them. ---

    if verdict == "weak":
        return "weak", "LLM weak (sticky)"

    if verdict == "unsupported":
        return "unsupported", "LLM unsupported (sticky)"

    if verdict == "overstates":
        # Legacy verdict from the existing prompt; we collapse it into
        # "weak" rather than introducing a new ensemble class. Reason
        # string preserves the original signal so audit logs don't lose
        # information.
        return "weak", "LLM overstates (legacy verdict, treated as weak)"

    if verdict == "contradicted":
        return "contradicted", "LLM contradicted (sticky)"

    # Defensive: any unexpected LLM verdict string falls through as "weak".
    if verdict != "supported":
        return "weak", f"LLM verdict {llm_verdict!r} not recognised; treated as weak"

    # --- LLM said supported. DeBERTa + lexical can downgrade. ---

    if label == "contradiction":
        # Any confidence — the cross-encoder's assertion that the chunk
        # contradicts the claim is a hard veto, regardless of how confident
        # it is. The reason captures the confidence so the operator can
        # decide whether to investigate.
        first_miss = _first_missing(num_missing)
        detail = first_miss or "see chunk"
        return "contradicted", f"DeBERTa contradicts ({conf:.2f}): {detail}"

    if label == "neutral":
        if num_score >= drift_below:
            return "weak", "DeBERTa neutral; LLM may have anchored on gist"
        return (
            "weak",
            f"DeBERTa neutral + numeric drift: {_missing_join(num_missing)}",
        )

    if label == "entailment":
        # W21/D3 conservative-default principle: if the DeBERTa
        # confidence is within ``[high_conf - band, high_conf)`` AND
        # numeric overlap is borderline (between drift_below and
        # drift_below + band), downgrade what would otherwise be a
        # supported_low to "weak". Uncertainty resolves toward
        # review, never toward trust. band=0.0 (the default) is a
        # no-op so pre-W21/D3 behaviour is preserved.
        in_conf_band = (high_conf - band) <= conf < high_conf
        # A perfect numeric overlap (1.0) is never borderline — it
        # means "no numerics in the claim" or "every claim numeric
        # matched the chunk." We only treat scores meaningfully
        # below 1.0 as borderline.
        in_num_band = (
            drift_below <= num_score < (drift_below + band)
            and num_score < 1.0
        )
        if band > 0 and (in_conf_band or in_num_band):
            reason_parts = []
            if in_conf_band:
                reason_parts.append(
                    f"DeBERTa conf {conf:.2f} in borderline band "
                    f"[{high_conf - band:.2f}, {high_conf:.2f})"
                )
            if in_num_band:
                reason_parts.append(
                    f"numeric overlap {num_score:.2f} borderline"
                )
            return (
                "weak",
                "conservative downgrade: " + " + ".join(reason_parts),
            )
        if conf >= high_conf and num_score >= drift_below:
            return "supported_high", "all signals agree"
        if conf >= high_conf and num_score < drift_below:
            return (
                "supported_low",
                f"numeric drift: missing {_missing_join(num_missing)}",
            )
        if conf < high_conf and num_score >= drift_below:
            return (
                "supported_low",
                f"DeBERTa low-confidence entailment ({conf:.2f})",
            )
        # conf < high_conf AND numeric drift — both soft signals fire, downgrade.
        return "weak", "DeBERTa weak entailment + numeric drift"

    # Unknown DeBERTa label (e.g. "unknown" sentinel from a worker timeout)
    # — treat the same as neutral to avoid silently passing.
    if num_score >= drift_below:
        return "weak", f"DeBERTa label {deberta.label!r} unrecognised; LLM may have anchored on gist"
    return (
        "weak",
        f"DeBERTa label {deberta.label!r} unrecognised + numeric drift: {_missing_join(num_missing)}",
    )
