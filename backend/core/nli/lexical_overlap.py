"""Precision-style lexical overlap signal for the verifier ensemble.

Phase 1 / Week 2 / Day 2. The third leg of the verification ensemble.
NLI judges (LLM and DeBERTa) anchor on gist; this signal anchors on
specifics — every numeric and named entity in the *claim* must have a
matching counterpart in the cited *chunk*, otherwise the claim has
introduced a fact the source doesn't support.

Scoring is precision-style:

    numeric_overlap_score = matches_in_claim / total_in_claim

If the claim has no numerics, ``numeric_overlap_score`` is 1.0 and
``numeric_missing`` is empty (we don't penalise a claim for not asserting
numbers it didn't try to assert). Same shape for entities.

Out of scope this week:
- Generic Jaccard / cosine on raw tokens. The whole point is precision
  on numerics and entities; generic similarity dilutes the signal.
- Coreference resolution. If the chunk says "the company" and the claim
  says "Stripe", we treat that as a miss. Real bugs hide under
  "the company" in claims, not in chunks.
- Inference (claim says "Mittelstand", chunk says "German mid-market
  firms"). That's the NLI judge's job. This signal is intentionally
  unforgiving — the operator wants a *different* error pattern from this
  signal than from the LLM/DeBERTa judges.

This module imports the numeric normalizer (pure regex) and the entity
extractor (spaCy). It does NOT import anything from
``backend/core/nli/deberta_client.py`` and never triggers the DeBERTa
cross-encoder load — verified via the smoke check in tools/. The
lexical signal lives in the main worker, the cross-encoder lives in
nli_worker, and the two paths are orthogonal.

A small but worth-knowing detail: importing this module DOES pull torch
into ``sys.modules`` as a transitive side-effect of importing spaCy
(thinc, spaCy's NN backend, probes for available tensor libraries when
torch is also installed in the env). The probe is cheap and en_core_web_sm
itself uses the numpy/blis backend, not torch. The 440MB DeBERTa MODEL
stays cold; the operative invariant — "lexical_overlap doesn't run the
cross-encoder" — holds. Process RSS after a score_overlap() call is
~300MB vs ~510MB once DeBERTa is loaded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.nli.entity_extractor import Entity, entities_match, extract_entities
from core.nli.numeric_normalizer import NumericValue, normalize, values_match


@dataclass(frozen=True)
class LexicalSignal:
    """One scored (claim, chunk) pair.

    Attributes
    ----------
    numeric_overlap_score:
        Fraction of claim numerics found in the chunk under the
        normalizer's tolerance rules. Range [0, 1].
    numeric_missing:
        ``raw_text`` of every claim numeric that did NOT find a chunk
        match. Surfaced verbatim so the operator can see exactly which
        figures the claim invented.
    entity_overlap_score:
        Fraction of claim entities (ORG/GPE/PRODUCT/LAW/NORP) found in
        the chunk after canonicalisation. Range [0, 1].
    entity_missing:
        ``raw_text`` of every claim entity that did NOT find a chunk
        match.
    """

    numeric_overlap_score: float
    numeric_missing: list[str] = field(default_factory=list)
    entity_overlap_score: float = 1.0
    entity_missing: list[str] = field(default_factory=list)


def _score_numerics(claim: str, chunk: str) -> tuple[float, list[str]]:
    claim_values = normalize(claim)
    if not claim_values:
        return 1.0, []
    chunk_values = normalize(chunk)
    matches = 0
    missing: list[str] = []
    for cv in claim_values:
        if any(values_match(cv, kv) for kv in chunk_values):
            matches += 1
        else:
            missing.append(cv.raw_text)
    return matches / len(claim_values), missing


def _score_entities(claim: str, chunk: str) -> tuple[float, list[str]]:
    claim_ents = extract_entities(claim)
    if not claim_ents:
        return 1.0, []
    chunk_ents = extract_entities(chunk)
    matches = 0
    missing: list[str] = []
    for ce in claim_ents:
        if any(entities_match(ce, ke) for ke in chunk_ents):
            matches += 1
        else:
            missing.append(ce.raw_text)
    return matches / len(claim_ents), missing


def score_overlap(claim: str, chunk: str) -> LexicalSignal:
    """Score one (claim, chunk) pair.

    The two component scorers are independent — a claim with a missing
    number but a present entity will get ``numeric_overlap_score < 1.0``
    and ``entity_overlap_score == 1.0``. Day 3 will combine these with
    the LLM and DeBERTa verdicts in the ensemble layer.
    """
    num_score, num_missing = _score_numerics(claim, chunk)
    ent_score, ent_missing = _score_entities(claim, chunk)
    return LexicalSignal(
        numeric_overlap_score=num_score,
        numeric_missing=num_missing,
        entity_overlap_score=ent_score,
        entity_missing=ent_missing,
    )
