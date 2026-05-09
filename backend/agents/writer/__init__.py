"""Writer agent + per-mode schema registry. Phase 2 / Week 7 / Day 1.

The pre-W7 single-file ``backend/agents/writer.py`` was promoted to a
package so the schemas/ subpackage can sit alongside the agent
without circular imports. ``from agents.writer import WriterAgent``
keeps working unchanged for every existing caller.
"""

from .agent import WRITER_SYSTEM, WriterAgent  # noqa: F401
from .schemas import (  # noqa: F401 — re-export public schema surface
    GeneralReportPayload,
    MAndADiligenceReportPayload,
    WriterReportBase,
    get_writer_schema,
)
