"""2x2 matrix framework payload — W8/D3.

A 2x2 is the universal consulting framework. The writer picks any two
discriminating dimensions (e.g. "strategic fit" vs "ease of
integration"), labels both axes + their poles, and assigns each item
(target, option, segment) to one of the four quadrants with a
rationale and an evidence trail.

Schema discipline:
- 2-12 items (a 2x2 with 1 item makes no sense; >12 stops being a 2x2
  and starts being a scatter plot — out of scope for v1).
- Every item needs evidence_citations (claim_id linkage from the
  analyst's key_claims).
- Quadrant is a strict Literal so the renderer can map directly to a
  grid cell without parsing free text.
- Axes need both label + the names of the low / high poles so the
  renderer can put "Low — Strategic fit — High" along the bottom
  edge without re-deriving the polarity from the data.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Quadrant = Literal["bottom_left", "bottom_right", "top_left", "top_right"]


class TwoByTwoItem(BaseModel):
    name: str = Field(..., min_length=2, max_length=80, description="Short label rendered inside the quadrant cell.")
    quadrant: Quadrant = Field(..., description="Which of the four cells this item sits in.")
    rationale: str = Field(
        ...,
        min_length=20,
        description="One- to two-sentence justification for the quadrant placement.",
    )
    evidence_citations: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "claim_id strings from analysis.key_claims that back the placement. "
            "Required and non-empty — schema rejects any item without a defensible trail."
        ),
    )

    model_config = {"extra": "ignore"}


class TwoByTwoMatrix(BaseModel):
    title: str = Field(..., min_length=4, max_length=120, description="Memo-facing title, e.g. 'Acquisition target screen'.")
    x_axis_label: str = Field(..., min_length=2, max_length=60, description="X-axis dimension, e.g. 'Strategic fit'.")
    x_axis_low_label: str = Field(..., min_length=1, max_length=30, description="Left-pole label, e.g. 'Low'.")
    x_axis_high_label: str = Field(..., min_length=1, max_length=30, description="Right-pole label.")
    y_axis_label: str = Field(..., min_length=2, max_length=60)
    y_axis_low_label: str = Field(..., min_length=1, max_length=30, description="Bottom-pole label.")
    y_axis_high_label: str = Field(..., min_length=1, max_length=30, description="Top-pole label.")
    items: list[TwoByTwoItem] = Field(..., min_length=2, max_length=12)
    interpretation: str = Field(
        ...,
        min_length=30,
        description="Narrative reading of the matrix — what the spread implies, where the cluster is, what to act on.",
    )

    model_config = {"extra": "ignore"}
