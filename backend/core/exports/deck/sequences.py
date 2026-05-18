"""Per-mode deck-sequence resolver — W11/D1.

Day 1 ships a minimal 3-slide sequence for every mode:
title -> exec_summary -> recommendation. Days 2-3 fill in mode-specific
slides (M&A: target_overview, synergy, valuation, integration; growth:
porters, options_matrix; common: critic_findings, sources).
"""

from __future__ import annotations

_DECK_SEQUENCES: dict[str, list[str]] = {
    # W11/D2: M&A deck has target_overview, financial_profile,
    # valuation_range, risks_matrix, integration_plan between
    # exec_summary and recommendation.
    # W11/D3: adds two_by_two_visual after valuation_range so the
    # partner sees the deal-shape 2x2 alongside the valuation triple.
    # Sequence length: 11 slides (under the 12-slide cap).
    "m_and_a_diligence": [
        "title",
        "exec_summary",
        "target_overview",
        "financial_profile",
        "valuation_range",
        "two_by_two_visual",
        "risks_matrix",
        "integration_plan",
        "recommendation",
        "next_steps",
        "sources",
    ],
    # W11/D2 used a text-stub options_matrix.
    # W11/D3 replaces it with the real porters_five_forces_visual.
    # Sequence length stays at 9.
    "growth_strategy": [
        "title",
        "exec_summary",
        "context",
        "market_landscape",
        "porters_five_forces_visual",
        "recommendation",
        "risks_matrix",
        "next_steps",
        "sources",
    ],
    # Boutique pricing reviews tend to share growth's structural shape
    # but skip market_landscape; collapses to the general fallback.
    # Uses two_by_two_visual when the writer produces a positioning
    # matrix (e.g. price vs. value 2x2).
    "boutique_pricing_review": [
        "title",
        "exec_summary",
        "context",
        "two_by_two_visual",
        "recommendation",
        "risks_matrix",
        "next_steps",
        "sources",
    ],
    # Market-entry — keeps market landscape and gains Porter's so the
    # partner sees the competitive structure for the new market.
    "market_entry": [
        "title",
        "exec_summary",
        "context",
        "market_landscape",
        "porters_five_forces_visual",
        "recommendation",
        "risks_matrix",
        "next_steps",
        "sources",
    ],
    # general: 7-slide minimum for unknown / mixed engagements.
    "general": [
        "title",
        "exec_summary",
        "context",
        "risks_matrix",
        "recommendation",
        "next_steps",
        "sources",
    ],
}


def get_deck_sequence_for_mode(mode_name: str | None) -> list[str]:
    """Return the ordered slide-name list for a consulting mode.
    Unknown / None modes fall back to ``general``."""
    key = (mode_name or "general").strip() or "general"
    return list(_DECK_SEQUENCES.get(key, _DECK_SEQUENCES["general"]))
