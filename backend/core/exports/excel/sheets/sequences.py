"""Per-mode workbook-sheet resolver — W12/D1.

Day 1 ships a minimal 2-sheet sequence for every mode: title +
assumptions. Day 2 adds Revenue Build + Cost Build. Day 3 adds
M&A-specific sheets (DCF, Comparables, Sensitivity). Day 4 ties
citation comments to every payload-derived cell.
"""

from __future__ import annotations

_WORKBOOK_SHEETS: dict[str, list[str]] = {
    # W12/D4: every mode gains a Summary sheet (mode-agnostic executive
    # landing page synthesizing recommendation + valuation + assumptions
    # + top-3 reasons/risks). Summary visually slots after Cover so a
    # partner opening the workbook lands on it second.
    # NOTE: Summary needs cell_registry entries that get populated by
    # downstream sheets (enterprise_value from DCF, wacc from
    # Assumptions, etc.). So it BUILDS last but DISPLAYS second — the
    # WorkbookBuilder reorders worksheets in finalize_branding()
    # using SUMMARY_VISUAL_INDEX below.
    "m_and_a_diligence": [
        "title", "assumptions", "revenue_build", "cost_build",
        "working_capital", "dcf", "comparables", "sensitivity",
        "synergies", "summary",
    ],
    "growth_strategy":        ["title", "assumptions", "revenue_build", "cost_build", "summary"],
    "boutique_pricing_review":["title", "assumptions", "revenue_build", "cost_build", "summary"],
    "market_entry":           ["title", "assumptions", "revenue_build", "cost_build", "summary"],
    "general":                ["title", "assumptions", "revenue_build", "cost_build", "summary"],
}

# Visual-order overrides: ``summary`` builds last but displays at
# index 1 (right after Cover). The WorkbookBuilder applies this in
# finalize_branding by moving the sheet to its target position.
SHEET_VISUAL_POSITION: dict[str, int] = {
    "summary": 1,
}


def get_workbook_sheets_for_mode(mode_name: str | None) -> list[str]:
    """Return the ordered list of sheet names for the given consulting
    mode. Unknown / None modes fall back to ``general``."""
    key = (mode_name or "general").strip() or "general"
    return list(_WORKBOOK_SHEETS.get(key, _WORKBOOK_SHEETS["general"]))
