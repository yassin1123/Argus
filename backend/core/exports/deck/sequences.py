"""Per-mode deck-sequence resolver — W11/D1.

Day 1 ships a minimal 3-slide sequence for every mode:
title -> exec_summary -> recommendation. Days 2-3 fill in mode-specific
slides (M&A: target_overview, synergy, valuation, integration; growth:
porters, options_matrix; common: critic_findings, sources).
"""

from __future__ import annotations

_DECK_SEQUENCES: dict[str, list[str]] = {
    # W11/D2: full M&A deck is 10 slides — target_overview, financial_profile,
    # valuation_range, risks_matrix, integration_plan slot between
    # exec_summary and recommendation so the partner reads the deal
    # shape before the verdict.
    "m_and_a_diligence": [
        "title",
        "exec_summary",
        "target_overview",
        "financial_profile",
        "valuation_range",
        "risks_matrix",
        "integration_plan",
        "recommendation",
        "next_steps",
        "sources",
    ],
    # W11/D2: 9-slide growth deck — context + market_landscape +
    # options_matrix replace the M&A-specific content slides.
    # options_matrix is a text stub today; W11/D3 replaces with a
    # 2x2 visual.
    "growth_strategy": [
        "title",
        "exec_summary",
        "context",
        "market_landscape",
        "options_matrix",
        "recommendation",
        "risks_matrix",
        "next_steps",
        "sources",
    ],
    # Boutique pricing reviews tend to share growth's structural shape
    # but skip market_landscape; collapses to the general fallback.
    "boutique_pricing_review": [
        "title",
        "exec_summary",
        "context",
        "options_matrix",
        "recommendation",
        "risks_matrix",
        "next_steps",
        "sources",
    ],
    # Market-entry sits between growth and general — keeps the market
    # landscape slide because the engagement type demands it.
    "market_entry": [
        "title",
        "exec_summary",
        "context",
        "market_landscape",
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
