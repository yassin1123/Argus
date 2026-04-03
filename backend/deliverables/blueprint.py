"""Unified deliverable blueprint: document + deck (composed from split modules)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from deliverables.deck_blueprint import build_deck_blueprint
from deliverables.models import DeliverableDocument
from deliverables.pptx_build import SlideBlueprint
from deliverables.report_blueprint import build_report_document, report_fingerprint


class DeliverableBlueprint(BaseModel):
    """First-class artifact: shared document body + slide intents before byte render."""

    document: DeliverableDocument
    slide_blueprint: SlideBlueprint
    fingerprint: str = ""
    appendix_source_count: int = 0
    finding_count: int = 0

    model_config = {"extra": "ignore"}

    def to_meta(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "slides": len(self.slide_blueprint.slides),
            "appendix_sources": self.appendix_source_count,
            "findings": self.finding_count,
            "slide_blueprint_version": self.slide_blueprint.version,
        }


def build_deliverable_blueprint(
    *,
    report: dict[str, Any],
    session_query: str,
    session_title: str,
) -> DeliverableBlueprint:
    doc = build_report_document(
        report=report, session_query=session_query, session_title=session_title
    )
    slides = build_deck_blueprint(doc=doc, report=report, session_query=session_query)
    fp = report_fingerprint(report)
    return DeliverableBlueprint(
        document=doc,
        slide_blueprint=slides,
        fingerprint=fp,
        appendix_source_count=len(doc.appendix_sources),
        finding_count=len(doc.findings),
    )
