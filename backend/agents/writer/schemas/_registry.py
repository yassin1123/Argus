"""Mode → writer schema registry.

The orchestrator looks up the resolved consulting mode's slug and asks
the registry for the right Pydantic class to validate the writer's
output against. Built-in modes share ``GeneralReportPayload`` until
they get their own bespoke schema; ``m_and_a_diligence`` is the first
mode to ship with a dedicated schema (W7/D1).

Unknown modes — including firm-defined modes that don't declare a
custom schema — fall back to ``GeneralReportPayload``. The fallback
is intentional: a firm shouldn't be unable to ship a memo just
because they registered a new mode slug we haven't taught the
registry about yet.
"""

from __future__ import annotations

from ._base import WriterReportBase
from ._general import GeneralReportPayload
from ._m_and_a import MAndADiligenceReportPayload

_SCHEMA_REGISTRY: dict[str, type[WriterReportBase]] = {
    "general": GeneralReportPayload,
    "market_entry": GeneralReportPayload,
    "due_diligence": GeneralReportPayload,
    "growth_strategy": GeneralReportPayload,
    "m_and_a_diligence": MAndADiligenceReportPayload,
}


def get_writer_schema(mode_name: str) -> type[WriterReportBase]:
    """Return the Pydantic schema class to validate the writer's output
    for ``mode_name``. Falls back to :class:`GeneralReportPayload` for
    unknown slugs (including firm-defined modes without a custom schema).
    """
    return _SCHEMA_REGISTRY.get(mode_name, GeneralReportPayload)
