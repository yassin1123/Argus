"""Deck exporter package — W11.

Public surface for everything outside ``core/exports/`` is the
``DeckPptxExporter`` registered against ``('deck', 'pptx')`` via the
top-level exports registry. The ``DeckBuilder`` and slide-registry
machinery are exposed for tests + future formats (e.g. PDF-of-deck).
"""

from __future__ import annotations

from .deck_builder import DeckBuilder
from .sequences import get_deck_sequence_for_mode
from .slides import (
    SlideBuilderBase,
    SlideResult,
    get_slide_builder,
    list_registered_slides,
    register_slide,
)

__all__ = [
    "DeckBuilder",
    "SlideBuilderBase",
    "SlideResult",
    "get_deck_sequence_for_mode",
    "get_slide_builder",
    "list_registered_slides",
    "register_slide",
]
