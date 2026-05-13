"""Slide builder base — W11/D1.

Each slide builder gets the shared (presentation, payload, branding,
citations) context and is responsible for adding ONE slide. The
return value lists the claim_ids cited from that slide so the
deck-level footnote pass (W11/D4) can stitch them into a consolidated
sources slide at the end.

Builders are pure-ish: they mutate ``presentation`` (which is the
whole point — that's where their slide lands) but they don't do IO.
The renderer doesn't know about specific slide types, only about
slide names ('title', 'exec_summary', etc.) keyed against the
registry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pptx.presentation import Presentation

    from .._base import ClaimCitation


@dataclass
class SlideResult:
    """What a slide builder returns to ``DeckBuilder``.

    ``slide_index`` is the 0-indexed position of the newly added
    slide in the presentation. ``citation_ids`` is the set of
    claim_ids referenced by content on this slide (deduplicated by
    the caller across slides).
    """

    slide_index: int
    citation_ids: list[str] = field(default_factory=list)


class SlideBuilderBase(ABC):
    """All slide builders subclass this. The builder is stateless
    (one instance per render is fine) and side-effects the
    presentation passed in."""

    slide_name: str = ""

    @abstractmethod
    def build(
        self,
        presentation: "Presentation",
        payload: Any,
        firm_branding: dict[str, Any],
        citations: "list[ClaimCitation]",
    ) -> SlideResult:
        raise NotImplementedError
