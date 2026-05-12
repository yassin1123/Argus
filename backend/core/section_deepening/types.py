"""Section-deepening request + result shapes — W9/D1.

The API layer receives :class:`DeepeningRequest`, immediately
persists a ``queued`` row in ``section_deepening_runs``, kicks off
the async :func:`service.deepen_section`, and returns the row id.
The frontend polls a GET endpoint that eventually returns a
:class:`DeepeningResult` with ``status="complete"`` (or
``"failed"`` with ``failure_reason`` set).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DeepeningRequest(BaseModel):
    """Inbound request from the consultant."""

    session_id: UUID = Field(..., description="Session whose report we're deepening.")
    section_path: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "Dotted path into the WriterReportBase payload, e.g. "
            "``synergy_estimate.cost_synergies`` or "
            "``target_overview.segments[2]``."
        ),
    )
    depth_directive: str | None = Field(
        None,
        max_length=4000,
        description=(
            "Consultant's freeform instruction — 'make this deeper "
            "because the client cares about working capital risk', "
            "etc. Stitched into the deepening writer prompt."
        ),
    )

    model_config = {"extra": "ignore"}


class DeepeningResult(BaseModel):
    """Outbound result the GET endpoint returns once the service
    completes (or fails)."""

    deepening_id: UUID
    section_path: str
    original_section_json: dict[str, Any] | list[Any] | str | int | float | bool | None
    deepened_section_json: dict[str, Any] | list[Any] | str | int | float | bool | None
    new_claim_ids: list[str] = Field(default_factory=list)
    new_evidence_chunks_used: int = 0
    cost_usd: float = 0.0
    wall_seconds: float = 0.0
    status: Literal["complete", "failed"]
    failure_reason: str | None = None

    model_config = {"extra": "ignore"}
