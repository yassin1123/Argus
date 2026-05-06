"""Lexical-overlap scorer fixture (Week 2 / Day 2).

15 (claim, chunk, expected_*) cases:
  - 5 perfect matches (every numeric AND every entity in the claim is
    present in the chunk).
  - 5 partial matches (some present, some missing on at least one of the
    two axes).
  - 5 misses (the claim asserts numerics or entities the chunk does not
    contain).

Two of the partials specifically exercise number-format variation: the
claim writes a number one way ("€2.4B") and the chunk writes it
differently ("€2,400 million") — the normalizer must canonicalise both
sides and report them as a match.

We assert ranges/sets rather than exact floats so a future regex tweak
that legitimately picks up an extra mention doesn't break the fixture.
"""

from __future__ import annotations

import math

import pytest

from core.nli.lexical_overlap import LexicalSignal, score_overlap


def _close(a: float, b: float, *, tol: float = 1e-6) -> bool:
    return math.isclose(a, b, abs_tol=tol)


# ---------------------------------------------------------------------------
# Perfect matches (5)
# ---------------------------------------------------------------------------


def test_perfect_country_only() -> None:
    """No numerics in claim; entity (Germany) in chunk. Both scores = 1.0."""
    claim = "Germany is the largest economy in Europe."
    chunk = "Germany leads continental Europe by GDP."
    sig = score_overlap(claim, chunk)
    assert sig.numeric_overlap_score == 1.0
    assert sig.entity_overlap_score == 1.0
    assert sig.numeric_missing == []
    assert sig.entity_missing == []


def test_perfect_money_match_same_format() -> None:
    claim = "Stripe processed $1 trillion in 2024."
    chunk = "In 2024, Stripe processed approximately $1 trillion in payment volume."
    sig = score_overlap(claim, chunk)
    assert sig.numeric_overlap_score == 1.0
    assert sig.entity_overlap_score == 1.0


def test_perfect_money_format_variation_eur() -> None:
    """Claim says €2.4B, chunk says €2,400 million. Same value, different
    surface form — the normalizer must canonicalise both to 2.4e9 EUR.

    Note: claim uses "Germany's" (not "German") so the spaCy GPE in claim
    (Germany) matches the spaCy GPE in chunk (Germany). "German" gets
    tagged as NORP, "Germany" as GPE — under strict precision-first
    canonicalisation those are different entities. Demonym/adjective
    folding is intentionally out of scope this week (see hard rules).
    """
    claim = "Germany's B2B SaaS market reached €2.4B in 2024."
    chunk = "Germany's B2B SaaS market hit €2,400 million in 2024."
    sig = score_overlap(claim, chunk)
    assert sig.numeric_overlap_score == 1.0, (
        f"format-variant money should match; got "
        f"score={sig.numeric_overlap_score}, missing={sig.numeric_missing}"
    )
    assert sig.entity_overlap_score == 1.0


def test_perfect_money_format_variation_usd() -> None:
    """Claim says $1B, chunk says 1,000 million dollars."""
    claim = "Stripe handled $1B in 2023 payments."
    chunk = "In 2023, Stripe processed 1,000 million dollars in payments."
    sig = score_overlap(claim, chunk)
    assert sig.numeric_overlap_score == 1.0, (
        f"got score={sig.numeric_overlap_score}, missing={sig.numeric_missing}"
    )


def test_perfect_percent_and_quarter() -> None:
    claim = "Q3 2024 revenue grew 30%."
    chunk = "In Q3 2024 the company posted 30 percent year-over-year revenue growth."
    sig = score_overlap(claim, chunk)
    assert sig.numeric_overlap_score == 1.0
    assert sig.entity_missing == []


# ---------------------------------------------------------------------------
# Partial matches (5)
# ---------------------------------------------------------------------------


def test_partial_one_of_two_numerics_missing() -> None:
    """Claim has two numerics; only one in chunk."""
    claim = "Stripe processed $1 trillion in 2024 with 30% growth."
    chunk = "Stripe processed $1 trillion in 2024."
    sig = score_overlap(claim, chunk)
    # 2 of 3 in claim (1 trillion + 2024 + 30%) → 2/3
    # ($1 trillion is MONEY, 2024 is DATE_YEAR, 30% is PERCENT — chunk has
    # the first two only)
    assert _close(sig.numeric_overlap_score, 2 / 3)
    assert any("30%" in m or "30" in m for m in sig.numeric_missing), (
        f"30% should be in missing; got {sig.numeric_missing}"
    )


def test_partial_entity_present_but_extra_numeric_missing() -> None:
    """Entity matches (Germany in both); extra claim number missing from chunk.

    spaCy en_core_web_sm tags Mittelstand context-sensitively (ORG-ish in
    claims like "Germany's Mittelstand has X" but unflagged in chunks
    like "Germany hosts a Mittelstand sector"), so we drop it from this
    fixture and let Germany alone carry the entity-match assertion. The
    cardinal "1,500 mid-market accounts" is the unmatched signal.
    """
    claim = "Germany has 1,500 mid-market accounts using competing tools."
    chunk = "Germany hosts a meaningful mid-market sector."
    sig = score_overlap(claim, chunk)
    assert sig.entity_overlap_score == 1.0, (
        f"Germany should match in both; got entity_missing={sig.entity_missing}"
    )
    # Claim has "1,500 mid-market" → CARDINAL 1500. Chunk has nothing numeric.
    assert sig.numeric_overlap_score < 1.0
    assert sig.numeric_missing  # at least one missing


def test_partial_money_within_tolerance_extra_year_missing() -> None:
    """€2.4B vs €2.42B is within ±2% tolerance (matches), but the claim's
    additional 2024 year reference is absent from the chunk.
    """
    claim = "The market reached €2.4B in 2024."
    chunk = "Recent reports peg the market at €2.42 billion."
    sig = score_overlap(claim, chunk)
    # €2.4B vs €2.42B match within tolerance; 2024 has no chunk match.
    assert sig.numeric_overlap_score < 1.0
    assert any(m == "2024" for m in sig.numeric_missing), (
        f"2024 should be missing; got {sig.numeric_missing}"
    )


def test_partial_one_of_two_entities_missing() -> None:
    """Two ORGs in claim (Apple, Microsoft); only Apple in chunk -> 1/2.

    spaCy en_core_web_sm reliably tags Apple/Microsoft as ORG. (It does
    NOT reliably tag every consulting-relevant company — Stripe / Adyen /
    Salesforce go untagged. We use the ones it knows to keep this fixture
    deterministic; entity-tagger gaps surface as a false-zero rather than
    a false-one, so the precision direction of the signal is preserved
    in production.)
    """
    claim = "Apple and Microsoft both compete in cloud platforms."
    chunk = "Apple is one of several large cloud platforms."
    sig = score_overlap(claim, chunk)
    assert sig.numeric_overlap_score == 1.0  # no numerics
    assert sig.entity_overlap_score < 1.0
    assert any("Microsoft" in m for m in sig.entity_missing), (
        f"Microsoft should be missing; got {sig.entity_missing}"
    )


def test_partial_quarter_matches_but_year_only_in_claim() -> None:
    """Claim has Q3 2024 AND a bare 2023 reference; chunk has only Q3 2024."""
    claim = "Revenue in Q3 2024 was €1B, up from €700M in 2023."
    chunk = "In Q3 2024 the company reported €1 billion in revenue."
    sig = score_overlap(claim, chunk)
    # Claim numerics: Q3 2024, €1B, €700M, 2023.
    # Chunk has Q3 2024 + €1B (or €1 billion). Missing: €700M, 2023.
    assert sig.numeric_overlap_score < 1.0
    assert sig.numeric_overlap_score >= 0.4, (
        f"at least Q3 2024 and €1B should match; got {sig.numeric_overlap_score}"
    )


# ---------------------------------------------------------------------------
# Misses (5) — claim asserts something the chunk doesn't support
# ---------------------------------------------------------------------------


def test_miss_invented_number() -> None:
    """Chunk has no number; claim does."""
    claim = "Germany has 1,500 Mittelstand accounts."
    chunk = "Germany hosts a meaningful Mittelstand sector."
    sig = score_overlap(claim, chunk)
    assert sig.numeric_overlap_score == 0.0
    assert sig.numeric_missing  # 1,500 must show up


def test_miss_invented_currency() -> None:
    """Claim says €1B; chunk has nothing about money."""
    claim = "The company raised €1B in 2024."
    chunk = "The company expanded its product line in 2024."
    sig = score_overlap(claim, chunk)
    # 2024 matches; €1B does not.
    assert sig.numeric_overlap_score < 1.0
    assert any("1B" in m or "1 B" in m or "€" in m for m in sig.numeric_missing), (
        f"€1B should be missing; got {sig.numeric_missing}"
    )


def test_miss_invented_country() -> None:
    """Claim names a country not present in the chunk."""
    claim = "France has the highest GDP in continental Europe."
    chunk = "Germany has the highest GDP in continental Europe."
    sig = score_overlap(claim, chunk)
    assert sig.entity_overlap_score < 1.0
    assert any("France" in m for m in sig.entity_missing), (
        f"France should be missing; got {sig.entity_missing}"
    )


def test_miss_wrong_company() -> None:
    """Claim attributes a fact to the wrong company.

    Apple / Microsoft both reliably ORG-tagged by en_core_web_sm. The
    numeric matches (both say $1 trillion); the company doesn't.
    """
    claim = "Microsoft processed $1 trillion in payments last year."
    chunk = "Apple processed $1 trillion in payments last year."
    sig = score_overlap(claim, chunk)
    assert sig.numeric_overlap_score == 1.0
    assert sig.entity_overlap_score < 1.0
    assert any("Microsoft" in m for m in sig.entity_missing), (
        f"Microsoft should be missing; got {sig.entity_missing}"
    )


def test_miss_money_outside_tolerance() -> None:
    """€2.4B vs €5B is well outside the ±2% MONEY tolerance."""
    claim = "The market reached €2.4B in 2024."
    chunk = "The market reached €5 billion in 2024."
    sig = score_overlap(claim, chunk)
    # 2024 matches; €2.4B doesn't match €5B → 0.5.
    assert _close(sig.numeric_overlap_score, 0.5)
    assert any("2.4" in m for m in sig.numeric_missing), (
        f"€2.4B should be missing; got {sig.numeric_missing}"
    )


# ---------------------------------------------------------------------------
# Empty-input behaviour
# ---------------------------------------------------------------------------


def test_empty_claim_returns_perfect_score() -> None:
    """A claim with no numerics and no entities should score 1.0/1.0 —
    there's nothing to penalise.
    """
    sig = score_overlap("Some opinion without specifics.", "Anything at all.")
    assert sig.numeric_overlap_score == 1.0
    assert sig.entity_overlap_score == 1.0
    assert sig.numeric_missing == []
    assert sig.entity_missing == []


def test_signal_dataclass_shape() -> None:
    sig = score_overlap("Stripe in 2024.", "Stripe in 2024.")
    assert isinstance(sig, LexicalSignal)
    # Field types and defaults — guards a future renaming/refactor.
    assert isinstance(sig.numeric_missing, list)
    assert isinstance(sig.entity_missing, list)
    assert 0.0 <= sig.numeric_overlap_score <= 1.0
    assert 0.0 <= sig.entity_overlap_score <= 1.0
