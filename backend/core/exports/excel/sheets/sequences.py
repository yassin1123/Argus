"""Per-mode workbook-sheet resolver — W12/D1.

Day 1 ships a minimal 2-sheet sequence for every mode: title +
assumptions. Day 2 adds Revenue Build + Cost Build. Day 3 adds
M&A-specific sheets (DCF, Comparables, Sensitivity). Day 4 ties
citation comments to every payload-derived cell.
"""

from __future__ import annotations

_WORKBOOK_SHEETS: dict[str, list[str]] = {
    # W12/D2: Revenue Build + Cost Build join the workbook. Both modes
    # get both sheets; the per-mode projection horizon (5y vs 3y) and
    # segment-vs-single-line shape are handled inside the sheet
    # builders rather than the sequence list.
    "m_and_a_diligence":      ["title", "assumptions", "revenue_build", "cost_build"],
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
