"""Per-mode workbook-sheet resolver — W12/D1.

Day 1 ships a minimal 2-sheet sequence for every mode: title +
assumptions. Day 2 adds Revenue Build + Cost Build. Day 3 adds
M&A-specific sheets (DCF, Comparables, Sensitivity). Day 4 ties
citation comments to every payload-derived cell.
"""

from __future__ import annotations

_WORKBOOK_SHEETS: dict[str, list[str]] = {
    # W12/D3: M&A mode gains 5 diligence-grade sheets (working_capital,
    # dcf, comparables, sensitivity, synergies). Other modes stay at
    # the 4-sheet baseline — they don't have the payload shape
    # (target_overview, valuation_range, synergy_estimate, etc.) the
    # DCF/synergies sheets need.
    "m_and_a_diligence": [
        "title", "assumptions", "revenue_build", "cost_build",
        "working_capital", "dcf", "comparables", "sensitivity", "synergies",
    ],
    "growth_strategy":        ["title", "assumptions", "revenue_build", "cost_build"],
    "boutique_pricing_review":["title", "assumptions", "revenue_build", "cost_build"],
    "market_entry":           ["title", "assumptions", "revenue_build", "cost_build"],
    "general":                ["title", "assumptions", "revenue_build", "cost_build"],
}


def get_workbook_sheets_for_mode(mode_name: str | None) -> list[str]:
    """Return the ordered list of sheet names for the given consulting
    mode. Unknown / None modes fall back to ``general``."""
    key = (mode_name or "general").strip() or "general"
    return list(_WORKBOOK_SHEETS.get(key, _WORKBOOK_SHEETS["general"]))
