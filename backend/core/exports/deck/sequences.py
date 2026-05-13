"""Per-mode deck-sequence resolver — W11/D1.

Day 1 ships a minimal 3-slide sequence for every mode:
title -> exec_summary -> recommendation. Days 2-3 fill in mode-specific
slides (M&A: target_overview, synergy, valuation, integration; growth:
porters, options_matrix; common: critic_findings, sources).
"""

from __future__ import annotations

_DECK_SEQUENCES: dict[str, list[str]] = {
    "m_and_a_diligence": ["title", "exec_summary", "recommendation"],
    "growth_strategy": ["title", "exec_summary", "recommendation"],
    "boutique_pricing_review": ["title", "exec_summary", "recommendation"],
    "market_entry": ["title", "exec_summary", "recommendation"],
    "general": ["title", "exec_summary", "recommendation"],
}


def get_deck_sequence_for_mode(mode_name: str | None) -> list[str]:
    """Return the ordered slide-name list for a consulting mode.
    Unknown / None modes fall back to ``general``."""
    key = (mode_name or "general").strip() or "general"
    return list(_DECK_SEQUENCES.get(key, _DECK_SEQUENCES["general"]))
