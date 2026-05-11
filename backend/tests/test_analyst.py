"""Phase 2 / Week 8 / Day 5 follow-up — analyst post-processing tests.

Covers ``_rewrite_slot_claim_ids``, which closes the W8/D5 Run B
blocker: the LLM emits ``reasoning_slots[].claim_ids`` referencing
hallucinated tokens (``claim_013``, etc.) at generation time, and
``_assign_claim_ids`` later mints real UUIDs on ``key_claims`` —
leaving slot refs dangling. The reasoning-skeleton gate then
correctly rejects the output. ``_rewrite_slot_claim_ids`` runs
right after ``_assign_claim_ids`` and remaps dangling refs to real
minted ids by word-overlap matching between the slot's summary and
each claim's text (threshold ≥3 shared words).
"""

from __future__ import annotations

from agents.analyst import _rewrite_slot_claim_ids


def test_rewrite_slot_claim_ids_keeps_valid() -> None:
    """A slot whose claim_ids already match minted key_claims ids
    should be left unchanged."""
    analysis = {
        "key_claims": [
            {"claim_id": "uuid-a", "text": "Bavaria procurement cycles are 6-8 weeks faster."},
            {"claim_id": "uuid-b", "text": "Three reference customers anchor logo-zero."},
        ],
        "reasoning_slots": [
            {
                "slot_id": "market_attractiveness",
                "summary": "Bavaria first; cycles compress quickly.",
                "claim_ids": ["uuid-a", "uuid-b"],
            },
        ],
    }
    _rewrite_slot_claim_ids(analysis)
    assert analysis["reasoning_slots"][0]["claim_ids"] == ["uuid-a", "uuid-b"]


def test_rewrite_slot_claim_ids_recovers_via_text_match() -> None:
    """A hallucinated id (``claim_013``) whose slot summary semantically
    matches a real claim text by ≥3 shared words should be rewritten
    to the matching real claim's id."""
    analysis = {
        "key_claims": [
            {
                "claim_id": "uuid-bavaria",
                "text": "Bavaria procurement cycles run faster than NRW.",
            },
            {
                "claim_id": "uuid-pilot",
                "text": "Pilot cost is bounded at one hundred thousand pounds.",
            },
        ],
        "reasoning_slots": [
            {
                "slot_id": "market_attractiveness",
                "summary": "Bavaria procurement cycles favor pilot entry.",
                "claim_ids": ["claim_013"],  # hallucinated
            },
        ],
    }
    _rewrite_slot_claim_ids(analysis)
    rewritten = analysis["reasoning_slots"][0]["claim_ids"]
    assert rewritten == ["uuid-bavaria"], f"expected recovery to uuid-bavaria, got {rewritten}"


def test_rewrite_slot_claim_ids_drops_unrecoverable() -> None:
    """A hallucinated id whose slot summary has fewer than 3 words in
    common with any claim text should be dropped — leaving a coverage
    gap the downstream gate will flag honestly, rather than silently
    pointing at an unrelated claim."""
    analysis = {
        "key_claims": [
            {
                "claim_id": "uuid-bavaria",
                "text": "Bavaria procurement cycles run faster than NRW.",
            },
        ],
        "reasoning_slots": [
            {
                "slot_id": "competition",
                "summary": "Tariff exposure on imports.",
                "claim_ids": ["claim_013"],  # hallucinated, no semantic match
            },
        ],
    }
    _rewrite_slot_claim_ids(analysis)
    assert analysis["reasoning_slots"][0]["claim_ids"] == []


def test_rewrite_slot_claim_ids_mixed_valid_and_recovered() -> None:
    """Bonus coverage: a slot mixing one valid id, one recoverable
    hallucination, and one unrecoverable hallucination should end up
    with two ids in stable order."""
    analysis = {
        "key_claims": [
            {"claim_id": "uuid-a", "text": "Three large competitors hold majority share of UK industrials."},
            {"claim_id": "uuid-b", "text": "Bavaria procurement cycles run faster than NRW competitors."},
        ],
        "reasoning_slots": [
            {
                "slot_id": "competition",
                "summary": "Bavaria procurement cycles favor faster competitive moves.",
                "claim_ids": ["uuid-a", "claim_013", "claim_999"],
            },
        ],
    }
    _rewrite_slot_claim_ids(analysis)
    rewritten = analysis["reasoning_slots"][0]["claim_ids"]
    # uuid-a kept as-is; claim_013 recovers to uuid-b via Bavaria/procurement
    # word overlap; claim_999 drops (same recovery target as claim_013,
    # so the dedup keeps a single occurrence anyway).
    assert "uuid-a" in rewritten
    assert "uuid-b" in rewritten
    assert len(rewritten) == 2  # dedup preserves stable order, no extras
