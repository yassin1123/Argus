"""Report models. Phase 2 / Week 7 / Day 1: ``WriterReportPayload`` is
now a deprecated alias that resolves to
``agents.writer.schemas.GeneralReportPayload``. Existing imports
(``from models.report import WriterReportPayload``) keep working
unchanged — same class, same validators, same JSON shape.

New callers should import from ``agents.writer.schemas`` directly and
use ``get_writer_schema(mode_name)`` to pick the right per-mode
class.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from typing import Any

# Re-export the helper item classes from the schema package so the
# legacy ``from models.report import SourceItem`` paths keep working.
from agents.writer.schemas import (  # noqa: F401 — public re-exports
    ExecutiveInsightItem,
    GeneralReportPayload,
    KeyRiskStructuredItem,
    SourceItem,
)

# Deprecated alias — use ``agents.writer.schemas.GeneralReportPayload``
# (or ``get_writer_schema(mode)`` when mode-aware) in new code.
WriterReportPayload = GeneralReportPayload


class ReportRow(BaseModel):
    id: UUID
    session_id: UUID
    recommendation: str
    confidence_level: str
    summary: str
    key_reasons: list[Any]
    risks: list[Any]
    counterarguments: list[Any]
    next_steps: list[Any]
    sources: list[Any]
    raw_output: str | None
    caveats: str
    created_at: datetime
