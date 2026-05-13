"""Deck PPTX exporter — W11/D1.

Top-level shim that plugs the deck builder into the W10 exporter
registry. The heavy lifting lives under ``core/exports/deck/`` so
this file stays small and changes when sequences / metadata fields
shift.
"""

from __future__ import annotations

from typing import Any

from ._base import ClaimCitation, ExporterBase, ExporterResult, payload_get
from ._registry import register
from .deck import DeckBuilder, get_deck_sequence_for_mode
from .one_pager_renderer import _detect_mode


@register("deck", "pptx")
class DeckPptxExporter(ExporterBase):
    """Render a consulting deck as a .pptx via python-pptx.

    Mode-aware sequence: M&A / growth_strategy / general all share a
    minimal 3-slide sequence on Day 1 (title, exec_summary,
    recommendation). Days 2-3 add mode-specific slides without
    touching this class — only ``sequences.py`` and the slide registry
    grow.
    """

    artifact_type = "deck"
    format = "pptx"

    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        mode_hint = payload_get(payload, "_mode_hint", default=None)
        mode = _detect_mode(payload, mode_hint)
        sequence = get_deck_sequence_for_mode(mode)

        builder = DeckBuilder(payload, firm_branding or {}, citations or [])
        for slide_name in sequence:
            builder.add_slide(slide_name)
        pptx_bytes = builder.serialize()

        return ExporterResult(
            file_bytes=pptx_bytes,
            file_size=len(pptx_bytes),
            claim_citation_count=builder.citation_count,
            metadata={
                "mode": mode,
                "slide_count": builder.slide_count,
                "slide_sequence": sequence,
                "cited_claim_ids": builder.cited_claim_ids,
            },
        )
