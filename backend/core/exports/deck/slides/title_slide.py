"""Title slide — W11/D1.

Layout:
  - Top primary-coloured band (16:9 width × 0.4 in tall).
  - Centred recommendation prose as the title text (or engagement
    title as the fallback when recommendation is blank).
  - Subtitle: target name + generated-on date.
  - Bottom: "Prepared by {firm name}".

No images embedded today (hard rule); a remote logo URL is treated
as text "[firm name]" so Day 1 never depends on network or asset
caching. Day 4 swaps in the cached-logo path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

from .._layout import (
    DEFAULT_MUTED,
    DEFAULT_PRIMARY,
    DEFAULT_SECONDARY,
    SLIDE_HEIGHT_IN,
    SLIDE_WIDTH_IN,
    add_blank_slide,
    add_horizontal_band,
    add_textbox,
    parse_hex,
)
from ..._base import payload_get
from ...one_pager_renderer import get_recommendation_text
from ._base import SlideBuilderBase, SlideResult
from ._registry import register_slide


@register_slide("title")
class TitleSlide(SlideBuilderBase):
    def build(
        self,
        presentation: Any,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[Any],
    ) -> SlideResult:
        primary = (firm_branding or {}).get("primary_color") or DEFAULT_PRIMARY
        secondary = (firm_branding or {}).get("secondary_color") or DEFAULT_SECONDARY
        firm_name = (
            (firm_branding or {}).get("_firm_name")
            or payload_get(payload, "_firm_name", default="Argus")
            or "Argus"
        )

        slide = add_blank_slide(presentation)

        # Top brand band.
        add_horizontal_band(
            slide,
            left=0.0,
            top=0.0,
            width=SLIDE_WIDTH_IN,
            height=0.4,
            color_hex=str(primary),
        )

        # Recommendation as the title; fall back to engagement title
        # if the writer hasn't produced a recommendation yet.
        rec = get_recommendation_text(payload) or str(
            payload_get(payload, "_engagement_title", default="Argus engagement")
        )
        # Truncate aggressively — the title slide must read at a glance.
        # Multi-sentence growth_strategy recommendations get the first
        # clause; the recommendation slide later carries the full prose.
        rec_short = rec.split(".")[0].strip()
        if len(rec_short) > 110:
            rec_short = rec_short[:107].rstrip() + "…"

        add_textbox(
            slide,
            left=0.7, top=2.0,
            width=SLIDE_WIDTH_IN - 1.4, height=2.0,
            text=rec_short,
            font_size=36, bold=True,
            color=parse_hex(secondary),
            align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE,
        )

        # Subtitle row: target name + date.
        target = (
            payload_get(payload, "_target_name", default="")
            or payload_get(payload, "_engagement_title", default="")
        )
        date_label = datetime.now(tz=timezone.utc).strftime("%B %Y")
        subtitle = " · ".join(p for p in (str(target), date_label) if p)
        add_textbox(
            slide,
            left=0.7, top=4.0,
            width=SLIDE_WIDTH_IN - 1.4, height=0.6,
            text=subtitle,
            font_size=16,
            color=parse_hex(DEFAULT_MUTED),
            align=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE,
        )

        # Bottom-left: "Prepared by <firm name>".
        add_textbox(
            slide,
            left=0.7,
            top=SLIDE_HEIGHT_IN - 0.7,
            width=SLIDE_WIDTH_IN - 1.4, height=0.4,
            text=f"Prepared by {firm_name}",
            font_size=11,
            color=parse_hex(DEFAULT_MUTED),
            align=PP_ALIGN.LEFT,
            anchor=MSO_ANCHOR.MIDDLE,
        )

        return SlideResult(slide_index=len(presentation.slides) - 1, citation_ids=[])
