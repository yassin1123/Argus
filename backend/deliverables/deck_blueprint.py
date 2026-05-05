"""Deck blueprint: slide intents derived from the deliverable document + report."""

from __future__ import annotations

from typing import Any

from deliverables.models import DeliverableDocument
from deliverables.pptx_build import SlideBlueprint, build_slide_blueprint_from_document


def build_deck_blueprint(
    *,
    doc: DeliverableDocument,
    report: dict[str, Any],
    session_query: str,
) -> SlideBlueprint:
    return build_slide_blueprint_from_document(
        doc=doc, report=report, session_query=session_query
    )
