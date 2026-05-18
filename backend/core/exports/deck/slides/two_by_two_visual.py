"""2x2 framework visual slide — W11/D3.

Replaces W11/D2's text-stub options_matrix on growth_strategy decks
and adds a parallel slot to the M&A sequence for the deal-shape 2x2
the W8 framework produces.

Reads ``payload.frameworks.two_by_two``. If absent the slide renders
a "not produced for this engagement" placeholder rather than an
empty grid — the fallback is the documented behaviour per the
W11/D3 spec hard rule.

Geometry (in inches on a 13.333 × 7.5 16:9 slide):
  - Title band  0.0   → 1.05
  - Grid        1.30  → 6.40   (5.1 in tall × 9.6 in wide)
  - Interpretation strip 6.55 → 7.20
"""

from __future__ import annotations

from typing import Any

from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

from .._layout import (
    DEFAULT_MUTED,
    DEFAULT_PRIMARY,
    DEFAULT_SECONDARY,
    SLIDE_WIDTH_IN,
    add_blank_slide,
    add_horizontal_band,
    add_textbox,
    parse_hex,
)
from ..shape_helpers import (
    add_citation_chip,
    add_quadrant_grid,
    add_text_in_box,
)
from ..._base import payload_get
from ...one_pager_renderer import _coerce_to_list
from ._base import SlideBuilderBase, SlideResult
from ._registry import register_slide

# Quadrant geometry tweaks: items get a small inner margin so they
# never touch the rectangle borders.
_QUADRANT_PADDING_IN = 0.08
# Items per quadrant — the W8 schema allows up to 12 items total;
# we cap per-cell at 3 so the slide stays readable.
_ITEMS_PER_QUADRANT = 3


def _group_items_by_quadrant(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        "top_left": [], "top_right": [],
        "bottom_left": [], "bottom_right": [],
    }
    for it in items:
        if not isinstance(it, dict):
            continue
        q = str(it.get("quadrant") or "").strip().lower()
        if q in grouped:
            grouped[q].append(it)
    return grouped


def _render_items_in_quadrant(
    slide: Any,
    region: dict[str, float],
    items: list[dict[str, Any]],
    cited: list[str],
    *,
    primary_hex: str, secondary_hex: str,
) -> None:
    if not items:
        return

    items = items[:_ITEMS_PER_QUADRANT]
    n = len(items)
    pad = _QUADRANT_PADDING_IN
    cell_left = region["left"] + pad
    cell_top = region["top"] + pad
    cell_width = region["width"] - 2 * pad
    cell_height = region["height"] - 2 * pad
    row_height = cell_height / n

    for i, it in enumerate(items):
        item_top = cell_top + i * row_height
        # Name (bold) — reserve top half of the row.
        name = str(it.get("name") or "").strip()[:60]
        rationale = str(it.get("rationale") or "").strip()
        cits = list(it.get("evidence_citations") or [])

        add_text_in_box(
            slide,
            left=cell_left, top=item_top,
            width=cell_width - 0.4, height=row_height * 0.4,
            text=name,
            font_size=11, bold=True,
            color=parse_hex(secondary_hex),
            align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
        )
        if rationale:
            add_text_in_box(
                slide,
                left=cell_left, top=item_top + row_height * 0.42,
                width=cell_width - 0.4, height=row_height * 0.55,
                text=rationale,
                font_size=9,
                color=parse_hex(DEFAULT_MUTED),
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
            )
        # Citation chip top-right of the row.
        if cits:
            cid = str(cits[0])
            if cid not in cited:
                cited.append(cid)
            add_citation_chip(
                slide,
                left=cell_left + cell_width - 0.34,
                top=item_top + 0.02,
                number=len(cited),
                claim_id=cid,
                primary_hex=primary_hex,
            )


@register_slide("two_by_two_visual")
class TwoByTwoVisualSlide(SlideBuilderBase):
    def build(
        self,
        presentation: Any,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[Any],
    ) -> SlideResult:
        primary = (firm_branding or {}).get("primary_color") or DEFAULT_PRIMARY
        secondary_hex = (firm_branding or {}).get("secondary_color") or DEFAULT_SECONDARY

        slide = add_blank_slide(presentation)
        add_horizontal_band(
            slide, left=0.0, top=0.0, width=SLIDE_WIDTH_IN, height=0.4,
            color_hex=str(primary),
        )

        # Pull the framework block. Tolerant of:
        #   payload.frameworks.two_by_two (the canonical writer shape).
        frameworks = payload_get(payload, "frameworks", default={}) or {}
        tb = frameworks.get("two_by_two") if isinstance(frameworks, dict) else None
        if not isinstance(tb, dict) or not _coerce_to_list(tb.get("items") or []):
            add_textbox(
                slide, left=0.5, top=0.5, width=SLIDE_WIDTH_IN - 1.0, height=0.5,
                text="Strategic Options Matrix",
                font_size=24, bold=True,
                color=parse_hex(secondary_hex),
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
            )
            add_textbox(
                slide, left=0.5, top=1.5, width=SLIDE_WIDTH_IN - 1.0, height=0.6,
                text="Strategic options matrix — not produced for this engagement.",
                font_size=12,
                color=parse_hex(DEFAULT_MUTED),
                align=PP_ALIGN.LEFT,
            )
            return SlideResult(slide_index=len(presentation.slides) - 1, citation_ids=[])

        # Title
        title = str(tb.get("title") or "Strategic Options")[:120]
        add_textbox(
            slide, left=0.5, top=0.5, width=SLIDE_WIDTH_IN - 1.0, height=0.5,
            text=title,
            font_size=24, bold=True,
            color=parse_hex(secondary_hex),
            align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
        )

        # Grid
        regions = add_quadrant_grid(
            slide,
            left=0.4, top=1.2,
            width=SLIDE_WIDTH_IN - 0.8, height=5.0,
            x_axis_label=str(tb.get("x_axis_label") or "X"),
            x_low_label=str(tb.get("x_axis_low_label") or "Low"),
            x_high_label=str(tb.get("x_axis_high_label") or "High"),
            y_axis_label=str(tb.get("y_axis_label") or "Y"),
            y_low_label=str(tb.get("y_axis_low_label") or "Low"),
            y_high_label=str(tb.get("y_axis_high_label") or "High"),
            primary_hex=str(primary),
        )

        items = [it for it in (tb.get("items") or []) if isinstance(it, dict)]
        grouped = _group_items_by_quadrant(items)

        cited: list[str] = []
        for quadrant_name, region in regions.items():
            _render_items_in_quadrant(
                slide, region, grouped.get(quadrant_name, []),
                cited,
                primary_hex=str(primary),
                secondary_hex=secondary_hex,
            )

        # Interpretation narrative — bottom strip below the grid.
        interp = str(tb.get("interpretation") or "").strip()
        if interp:
            add_text_in_box(
                slide,
                left=0.5, top=6.65,
                width=SLIDE_WIDTH_IN - 1.0, height=0.55,
                text=interp,
                font_size=10,
                color=parse_hex(DEFAULT_MUTED),
                align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
            )

        return SlideResult(slide_index=len(presentation.slides) - 1, citation_ids=cited)
