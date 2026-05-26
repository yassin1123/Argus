"""Reason-then-verdict LLM judge — Phase 5 / Week 22 / Day 3.

The W22/D2 diagnosis named the highest-leverage fix: a structured,
reason-before-verdict LLM judgment that forces the model to (1)
restate the claim as testable parts, (2) quote the supporting
span from the evidence (or declare none), (3) only THEN emit the
verdict. The same discipline lands the heuristic substitute
(used when API keys aren't available) so the cached-score
calibration improves on the W21 baseline + the real-ensemble
path inherits the same structure.

Why a structured prompt is the highest-leverage fix on a
multi-front diagnosis:

  - LLM-entailment faults — direct fix. "Looks related → supported"
    is the failure mode the structured prompt prevents.
  - Evidence faults — indirect fix. Asking "which specific span
    supports this?" forces span attention; if no span exists, the
    model declares it (instead of vibing toward supported).
  - Lexical false-friends — indirect fix. Demanding a quoted
    supporting span forces semantic matching, not gist overlap.
  - Aggregation faults — orthogonal (not touched).
  - DeBERTa faults — orthogonal (the cross-encoder isn't an LLM
    prompt concern).

So the prompt change is a single focused fix that touches three
of the five W22/D2 fault categories at once. That's
"highest-leverage" in a multi-front setting.

Module surface:

  - :data:`REASON_THEN_VERDICT_SYSTEM` — the production prompt
    for ``RealEnsembleVerifier`` (W22/D1 + D3).
  - :func:`heuristic_reason_then_verdict` — deterministic
    no-LLM substitute that mirrors the prompt's discipline:
    decompose claim → look for supporting span → judge per part.
    Used by the heuristic verifier so the cached-score path also
    benefits from the W22/D3 work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Production prompt
# ---------------------------------------------------------------------------


REASON_THEN_VERDICT_SYSTEM = """\
You verify a CLAIM against EVIDENCE in three structured steps. Do NOT skip a step.

STEP 1 — DECOMPOSE the CLAIM into its testable parts. If the claim has
multiple conjuncts ("both X and Y", "X, Y, and Z"), each conjunct is a
separate part. If the claim asserts a magnitude or a specific number,
that number is part of the assertion (not optional). If the claim
attributes a statement to a specific person/source, the attribution is
part of the assertion.

STEP 2 — For each part, QUOTE the specific sentence(s) from the
EVIDENCE that would establish that part. If no sentence in the EVIDENCE
establishes a part, write exactly: "no supporting span" for that part.

A "supporting span" must establish the SPECIFIC assertion, not just
mention the topic. Evidence that says "FY2023 results were presented"
does NOT establish "FY2023 revenue grew 12%". Evidence that says
"the CEO mentioned dividend policy" does NOT establish "the CFO
guided to a 4% dividend yield".

STEP 3 — JUDGE based on Steps 1 + 2. Emit ONE of these verdicts:

  - "supported"    — every part of the claim has a supporting span that
                     directly establishes it. Magnitudes match.
                     Attributions match. No part missing.
  - "weak"         — at least one part is partially established (direction
                     right but magnitude wrong, topic mentioned but the
                     specific assertion not stated, attribution right but
                     fact slightly different).
  - "unsupported"  — the evidence is topically related but does not
                     establish the specific assertion.
  - "contradicted" — the evidence states the opposite of any part of
                     the claim (e.g., claim says "grew", evidence says
                     "declined"; claim says "approved", evidence says
                     "rejected").

Return ONLY valid JSON in this exact shape (no commentary outside):
{
  "claim_parts": ["<part 1>", "<part 2>", ...],
  "supporting_spans": ["<quoted span 1 or 'no supporting span'>", ...],
  "verdict": "supported | weak | unsupported | contradicted",
  "rationale": "<one-sentence reasoning naming any missing/mismatched parts>"
}
"""


# ---------------------------------------------------------------------------
# Heuristic substitute — implements the same reason-before-verdict
# discipline using deterministic text features (no LLM)
# ---------------------------------------------------------------------------


_CONJUNCTION_CUES = re.compile(
    r"\b(?:both\s+\w+\s+and\s+\w+"
    r"|across\s+(?:all|every))\b",
    re.IGNORECASE,
)
_QUANTIFIER_CUES = (
    "every", " all ", "across all", "across every", "best-in-class",
    "dominates", "leads", "highest", "lowest",
)
_CAUSAL_CUES = (
    " drove ", " driven by ", " caused ", " due to ", " because ",
    " led to ", " resulted in ", " responsible for ",
)
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(?:\$|£|€)?\s?\d+(?:\.\d+)?(?:%|\s?(?:bps|basis points|m|bn|k))?"
    r"(?![A-Za-z])"
)
_STRONG_NEGATION_CUES = (
    " not ", " no ", " never ", " did not ", "didn't",
    " declined ", " fell ", " dropped ", " rejected ",
    " qualified opinion ",
    # W22/D3 additions — caught the red-team escapes after the
    # reason-then-verdict rework softened the direction check.
    " slipped ", " slipped by ",
    " not approved ", " did not approve ",
    " unchanged ", " unchanged at ",   # "rating was unchanged"
    " has slipped ", " has not ",
)

# Year/period tokens we extract to detect temporal-drift attacks
# (claim says FY2024, evidence is about FY2023). A claim that
# names a period the evidence doesn't carry is insufficient.
_PERIOD_RE = re.compile(
    r"\b(?:FY\d{4}|Q[1-4]\s*FY\d{4}|Q[1-4]\s*\d{4}|"
    r"H[12]\s*FY\d{4}|H[12]\s*\d{4})\b",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", " " + (s or "").lower() + " ")


def _claim_numbers(claim: str) -> list[str]:
    return [m.group(0).strip() for m in _NUMBER_RE.finditer(claim or "")]


def _evidence_has_number(num: str, evidence_norm: str) -> bool:
    """Does the evidence contain this exact figure (or a normalised
    form of it)? Cheap version of what the lexical signal does;
    used here for per-part judgement, not the cross-claim lexical
    overlap score."""
    n = num.strip().lstrip("£$€").rstrip(",.")
    return n.lower() in evidence_norm


@dataclass
class HeuristicJudgment:
    """The verdict + the trace of which parts were checked.
    Mirrors what the real-LLM prompt's JSON response provides."""

    verdict: str
    rationale: str
    claim_parts: list[str]
    supporting_spans: list[str]    # "no supporting span" for misses


def heuristic_reason_then_verdict(
    claim: str, evidence: str,
) -> HeuristicJudgment:
    """Deterministic substitute for the structured LLM judgment.
    Implements the same discipline as :data:`REASON_THEN_VERDICT_SYSTEM`
    but with rule-based features instead of an LLM.

    Pipeline:

      1. Decompose: split the claim on " and ", "; " etc. into
         parts. A single-clause claim is one part.
      2. For each part, find a supporting span: look for the
         strongest sentence overlap in the evidence. Score the
         span — does it ESTABLISH the part, or just MENTION the
         topic?
      3. Judge:
         - any part contradicted (evidence has opposing direction)
           → ``contradicted``
         - any part has a number not in the evidence → ``weak``
         - any quantifier ("every", "across all") with mismatch
           → ``weak``
         - any causal verb ("drove", "caused") without explicit
           causal language in the evidence → ``weak`` (the
           "correlation not causation" failure)
         - any part without a supporting span (topic mentioned but
           specific not stated) → ``unsupported`` (or ``weak`` if
           some other parts ARE supported)
         - all parts supported → ``supported``
    """
    parts = _decompose_claim(claim)
    e = _norm(evidence)

    # --- per-part judgement ---
    spans: list[str] = []
    part_verdicts: list[str] = []  # one of: supported/partial/insufficient/contradicted
    rationales: list[str] = []
    for part in parts:
        verdict_for_part, span, reason = _judge_part(part, evidence, e)
        part_verdicts.append(verdict_for_part)
        spans.append(span)
        rationales.append(reason)

    # --- combine part verdicts into one ---
    if any(v == "contradicted" for v in part_verdicts):
        final = "contradicted"
    elif all(v == "supported" for v in part_verdicts):
        final = "supported"
    elif any(v == "supported" for v in part_verdicts) and any(
        v in {"partial", "insufficient"} for v in part_verdicts
    ):
        # Some parts established, others not → partial / weak.
        final = "weak"
    elif any(v == "partial" for v in part_verdicts):
        final = "weak"
    else:
        final = "unsupported"

    return HeuristicJudgment(
        verdict=final,
        rationale=" | ".join(rationales),
        claim_parts=parts,
        supporting_spans=spans,
    )


def _decompose_claim(claim: str) -> list[str]:
    """Split a claim into testable parts. Conservative: only
    splits on " and "/" but "/" and "/";" between two clauses
    that each contain a verb-shape — single-clause claims pass
    through as one part."""
    if not claim:
        return []
    # Drop trailing punctuation noise.
    text = claim.strip().rstrip(".!?")
    # Match conjunctive "both X and Y" — split into ["X", "Y"]
    both_match = re.match(
        r"^(.*?)\s+both\s+(.+?)\s+and\s+(.+)$", text, re.IGNORECASE,
    )
    if both_match:
        prefix, a, b = both_match.groups()
        prefix = prefix.strip()
        if prefix:
            return [f"{prefix} {a}".strip(), f"{prefix} {b}".strip()]
        return [a.strip(), b.strip()]
    # Multi-part conjunctions ("X, Y, and Z") — only when commas
    # join clauses with the "and" connector.
    if " and " in text and "," in text:
        chunks = [c.strip() for c in re.split(r",|\sand\s", text) if c.strip()]
        if len(chunks) >= 2 and all(len(c.split()) >= 3 for c in chunks):
            return chunks
    return [text]


def _judge_part(
    part: str, evidence_raw: str, evidence_norm: str,
) -> tuple[str, str, str]:
    """Return (verdict_for_part, span_or_marker, rationale)."""
    part_norm = _norm(part)

    # --- temporal-drift check ---
    # If the claim names a period (FY2024, Q3 FY2023, ...) and the
    # evidence carries DIFFERENT periods only, the claim is talking
    # about the wrong time window. The W21/D4 red-team's
    # temporal-drift cases live in this branch.
    claim_periods = {
        m.group(0).upper().replace(" ", "")
        for m in _PERIOD_RE.finditer(part or "")
    }
    if claim_periods:
        evidence_periods = {
            m.group(0).upper().replace(" ", "")
            for m in _PERIOD_RE.finditer(evidence_raw or "")
        }
        if evidence_periods and not (claim_periods & evidence_periods):
            return (
                "insufficient",
                "no supporting span (claim names a period the "
                "evidence doesn't cover)",
                f"period mismatch: claim={sorted(claim_periods)} "
                f"evidence={sorted(evidence_periods)}",
            )

    # --- contradiction check ---
    # If evidence has a negation cue tied to a topic word in the
    # claim, treat as contradicted.
    has_negation = any(neg in evidence_norm for neg in _STRONG_NEGATION_CUES)
    direction_words = (
        "grew", "growth", "rose", "increase", "expanded", "approved",
        "endorsed", "supported", "on schedule", "completed",
        "is on track", "downgraded",
    )
    claim_asserts_growth = any(w in part_norm for w in direction_words)
    evidence_says_decline = any(
        d in evidence_norm
        for d in (
            " declined ", " fell ", " dropped ", " rejected ",
            " slipped ", " has slipped ", " unchanged ",
            " did not approve ", " has not ",
        )
    )
    if claim_asserts_growth and evidence_says_decline:
        return (
            "contradicted",
            "no supporting span (evidence states the opposite direction)",
            "contradicted by evidence direction",
        )
    if " rejected " in part_norm and " approved " in evidence_norm:
        return (
            "contradicted",
            "no supporting span (evidence states approval, not rejection)",
            "contradicted by evidence",
        )

    # --- numeric check ---
    nums = _claim_numbers(part)
    if nums:
        missing = [n for n in nums if not _evidence_has_number(n, evidence_norm)]
        if missing:
            return (
                "partial",
                "no supporting span",
                f"missing number(s) in evidence: {', '.join(missing[:3])}",
            )

    # --- causal check ---
    has_causal_verb = any(c in part_norm for c in _CAUSAL_CUES)
    if has_causal_verb:
        # Evidence must explicitly carry causal language too.
        evidence_has_causal = any(c in evidence_norm for c in _CAUSAL_CUES)
        if not evidence_has_causal:
            return (
                "insufficient",
                "no supporting span (claim is causal; evidence "
                "states events but not the link)",
                "causal verb present in claim without causal "
                "language in evidence",
            )

    # --- universal-quantifier check ---
    has_quantifier = any(q in part_norm for q in _QUANTIFIER_CUES)
    if has_quantifier:
        # Heuristic: if claim says "every X" / "across all X" / "best",
        # the evidence must say something supporting universality.
        evidence_supports_universal = any(
            cue in evidence_norm
            for cue in (
                " every ", " all ", " each ", " across all ",
                "best-in-class", " #1 ", " number one ",
            )
        )
        if not evidence_supports_universal:
            return (
                "partial",
                "no supporting span (claim asserts universality; "
                "evidence supports only some cases)",
                "universal quantifier without universal evidence",
            )

    # --- topic overlap check ---
    # Rough proxy: if the claim's content words have any presence
    # in the evidence, we count it as "topically present"; otherwise
    # the claim isn't even on-topic for this chunk.
    c_tokens = set(re.findall(r"[a-z0-9]+", part_norm)) - {
        "the", "and", "of", "to", "in", "for", "on", "by",
        "is", "was", "a", "an", "at", "as", "be", "with",
        "that", "this", "its", "from",
    }
    e_tokens = set(re.findall(r"[a-z0-9]+", evidence_norm))
    overlap = (
        len(c_tokens & e_tokens) / len(c_tokens) if c_tokens else 1.0
    )
    if overlap < 0.35:
        return (
            "insufficient",
            "no supporting span (chunk not on-topic for claim)",
            f"low token overlap {overlap:.2f}",
        )

    # Synthesize a "supporting span" by picking the evidence
    # sentence with the highest token overlap with the part.
    sentences = re.split(r"(?<=[.!?])\s+", evidence_raw or "")
    best_span = ""
    best_score = 0
    for sent in sentences:
        s_tokens = set(re.findall(r"[a-z0-9]+", sent.lower()))
        score = len(c_tokens & s_tokens)
        if score > best_score:
            best_score = score
            best_span = sent.strip()
    if not best_span:
        return (
            "insufficient",
            "no supporting span",
            "no sentence in evidence overlaps with claim",
        )
    return ("supported", best_span[:200], "supporting span found")


__all__ = [
    "HeuristicJudgment",
    "REASON_THEN_VERDICT_SYSTEM",
    "heuristic_reason_then_verdict",
]
