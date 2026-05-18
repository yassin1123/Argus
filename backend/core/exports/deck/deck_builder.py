"""DeckBuilder — wraps a pptx ``Presentation``, dispatches per-slide
builders by name, accumulates citations across slides, and serializes
the deck to bytes.

W11/D1: thin orchestrator. Mode-specific sequencing comes from
``sequences.get_deck_sequence_for_mode``; per-slide construction is
fully delegated to the slide-builder registry. The DeckBuilder
itself owns no slide-specific layout knowledge.
"""

from __future__ import annotations

import io
from typing import Any

from pptx import Presentation

from ._layout import set_slide_size_16_9
from .slides import get_slide_builder, list_registered_slides  # noqa: F401
from .slides._base import SlideResult


class DeckBuilder:
    """Wraps a ``pptx.Presentation``. Each ``add_slide(name)`` call
    looks the builder up in the slide registry and runs it against
    the shared payload + branding + citations context."""

    def __init__(
        self,
        payload: Any,
        firm_branding: dict[str, Any] | None,
        citations: list[Any] | None,
    ) -> None:
        self._payload = payload
        self._branding = dict(firm_branding or {})
        self._citations = list(citations or [])
        self._presentation = Presentation()
        set_slide_size_16_9(self._presentation)
        self._results: list[SlideResult] = []
        self._slide_names_ordered: list[str] = []
        self._all_citation_ids: list[str] = []
        self._seen_citation_ids: set[str] = set()

    @property
    def presentation(self) -> Presentation:
        return self._presentation

    @property
    def slide_count(self) -> int:
        return len(self._presentation.slides)

    @property
    def citation_count(self) -> int:
        return len(self._all_citation_ids)

    @property
    def cited_claim_ids(self) -> list[str]:
        return list(self._all_citation_ids)

    @property
    def slide_names(self) -> list[str]:
        """The ordered list of slide_name strings actually rendered.
        Useful for tests + the artifact metadata block. Tracked on
        the builder itself because pptx ``Slide`` objects use C-level
        proxies that reject arbitrary attribute assignment."""
        return list(self._slide_names_ordered)

    def add_slide(self, slide_name: str) -> SlideResult:
        builder_cls = get_slide_builder(slide_name)
        builder = builder_cls()
        result = builder.build(
            self._presentation,
            self._payload,
            self._branding,
            self._citations,
        )
        self._results.append(result)
        self._slide_names_ordered.append(slide_name)
        for cid in result.citation_ids:
            if cid and cid not in self._seen_citation_ids:
                self._seen_citation_ids.add(cid)
                self._all_citation_ids.append(cid)
        return result

    def serialize(self) -> bytes:
        buf = io.BytesIO()
        self._presentation.save(buf)
        return buf.getvalue()
