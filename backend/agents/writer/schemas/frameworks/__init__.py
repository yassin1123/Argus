"""Structured-framework payloads — Phase 2 / Week 8 / Day 3.

Three first-class frameworks land in this module:

- :class:`TwoByTwoMatrix` — generic 2x2 with named axes and quadrant-
  assigned items.
- :class:`PortersFiveForcesAnalysis` — industry-attractiveness frame.
- :class:`ValueChainAnalysis` — Porter value chain across primary +
  support activities.

All three are wrapped in :class:`FrameworksPayload` which is mounted
as an optional field on :class:`WriterReportBase`. Backward-compat is
preserved: every existing payload defaults ``frameworks=None`` and
deserialises unchanged.

The renderer tier (``frontend/components/MemoRenderer/Frameworks/``)
dispatches off these classes; a payload with
``frameworks.two_by_two`` non-null renders the 2x2 component, etc.
"""

from __future__ import annotations

from pydantic import BaseModel

from ._porters_five_forces import (  # noqa: F401
    ForceAssessment,
    PortersFiveForcesAnalysis,
)
from ._two_by_two import TwoByTwoItem, TwoByTwoMatrix  # noqa: F401
from ._value_chain import ValueChainActivity, ValueChainAnalysis  # noqa: F401


class FrameworksPayload(BaseModel):
    """Optional container for structured frameworks the writer chose to
    emit alongside the narrative. Each slot is independently optional —
    a memo may carry one, two, or all three; or none.
    """

    two_by_two: TwoByTwoMatrix | None = None
    porters_five_forces: PortersFiveForcesAnalysis | None = None
    value_chain: ValueChainAnalysis | None = None

    model_config = {"extra": "ignore"}
