"""Per-mode workbook-sheet resolver — W12/D1.

Day 1 ships a minimal 2-sheet sequence for every mode: title +
assumptions. Day 2 adds Revenue Build + Cost Build. Day 3 adds
M&A-specific sheets (DCF, Comparables, Sensitivity). Day 4 ties
citation comments to every payload-derived cell.
"""

from __future__ import annotations

_WORKBOOK_SHEETS: dict[str, list[str]] = {
    "m_and_a_diligence": ["title", "assumptions"],
    "growth_strategy":   ["title", "assumptions"],
    "boutique_pricing_review": ["title", "assumptions"],
    "market_entry":      ["title", "assumptions"],
    "general":           ["title", "assumptions"],
}


def get_workbook_sheets_for_mode(mode_name: str | None) -> list[str]:
    """Return the ordered list of sheet names for the given consulting
    mode. Unknown / None modes fall back to ``general``."""
    key = (mode_name or "general").strip() or "general"
    return list(_WORKBOOK_SHEETS.get(key, _WORKBOOK_SHEETS["general"]))
