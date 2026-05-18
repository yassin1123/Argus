"""Slide builder base — W11/D1 + D4.

Each slide builder gets the shared (presentation, payload, branding,
citations) context and is responsible for adding ONE slide. The
return value lists the claim_ids cited from that slide; the
``DeckBuilder`` aggregates these so the W11/D4 per-slide footnote
strip can render the right citation breadcrumbs above the footer.

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
    the caller across slides). ``skip_chrome`` lets a builder
    (title slide) opt out of the standard title-bar + footer + footnotes
    pass.
    """

    slide_index: int
    citation_ids: list[str] = field(default_factory=list)
    skip_chrome: bool = False


class SlideBuilderBase(ABC):
    """All slide builders subclass this. The builder is stateless
    (one instance per render is fine) and side-effects the
    presentation passed in.

    W11/D4: the ``deck_context`` kwarg threads the per-deck citation
    registry into each builder so chip numbers and footnote
    breadcrumbs stay in sync across slides. Builders that don't
    need the registry can ignore the kwarg; the base resolves the
    default to ``None``.
    """

    slide_name: str = ""

    @abstractmethod
    def build(
        self,
        presentation: "Presentation",
        payload: Any,
        firm_branding: dict[str, Any],
        citations: "list[ClaimCitation]",
        deck_context: "DeckContext | None" = None,
    ) -> SlideResult:
        raise NotImplementedError


@dataclass
class DeckContext:
    """Per-deck mutable context threaded into each slide builder.

    Carries the deck-wide citation registry so slide builders can
    register the claim_ids they cite and get back the chip number
    they should display. ``citation_breadcrumbs`` maps a claim_id to
    its human-readable source string (built from
    ``ClaimCitation.source_title`` / ``source_type``).
    """

    citation_numbers: dict[str, int] = field(default_factory=dict)
    citation_breadcrumbs: dict[str, str] = field(default_factory=dict)
    per_slide_chip_numbers: list[list[int]] = field(default_factory=list)

    def assign_chip(self, claim_id: str, breadcrumb: str = "") -> int:
        """Return the chip number for this claim_id, assigning a new
        one if it hasn't been seen yet. Number is the citation's
        position in the deck-wide registry (1-indexed)."""
        cid = (claim_id or "").strip()
        if not cid:
            return 0
        if cid not in self.citation_numbers:
            self.citation_numbers[cid] = len(self.citation_numbers) + 1
            if breadcrumb:
                self.citation_breadcrumbs[cid] = breadcrumb
        elif breadcrumb and cid not in self.citation_breadcrumbs:
            self.citation_breadcrumbs[cid] = breadcrumb
        return self.citation_numbers[cid]

    def start_slide(self) -> None:
        self.per_slide_chip_numbers.append([])

    def record_chip_on_current_slide(self, number: int) -> None:
        if not self.per_slide_chip_numbers:
            self.per_slide_chip_numbers.append([])
        if number and number not in self.per_slide_chip_numbers[-1]:
            self.per_slide_chip_numbers[-1].append(number)

    def footnotes_for_current_slide(self) -> list[tuple[int, str]]:
        if not self.per_slide_chip_numbers:
            return []
        chips = self.per_slide_chip_numbers[-1]
        # Resolve number -> claim_id by reverse-mapping the registry.
        rev = {n: cid for cid, n in self.citation_numbers.items()}
        out: list[tuple[int, str]] = []
        for n in sorted(chips):
            cid = rev.get(n, "")
            label = self.citation_breadcrumbs.get(cid) or cid or "—"
            out.append((n, label))
        return out
