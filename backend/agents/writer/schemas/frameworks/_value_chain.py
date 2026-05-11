"""Value Chain framework payload — W8/D3.

Porter's value chain split into primary + support activities. Each
activity is bound to a canonical step (so the renderer can group the
two rows correctly without parsing prose) and carries an assessment
+ competitive implication + evidence trail.

Canonical steps follow Porter's original taxonomy:
- Primary: inbound_logistics, operations, outbound_logistics,
  marketing_and_sales, service
- Support: firm_infrastructure, hr_management,
  technology_development, procurement

Schema discipline:
- ≥4 activities (a memo claiming "value-chain analysis" with one
  activity is performance art, not analysis).
- Every activity needs evidence_citations (claim_id linkage).
- canonical_step is a strict Literal so the renderer can assign each
  card to the correct row + column position deterministically.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ActivityCategory = Literal["primary", "support"]

CanonicalStep = Literal[
    # Primary
    "inbound_logistics",
    "operations",
    "outbound_logistics",
    "marketing_and_sales",
    "service",
    # Support
    "firm_infrastructure",
    "hr_management",
    "technology_development",
    "procurement",
]


class ValueChainActivity(BaseModel):
    name: str = Field(..., min_length=2, max_length=80, description="Activity label as it appears on the card.")
    category: ActivityCategory = Field(..., description="Top-row 'primary' or bottom-row 'support'.")
    canonical_step: CanonicalStep = Field(
        ...,
        description="Which Porter canonical step this activity maps to (drives renderer grouping).",
    )
    assessment: str = Field(
        ...,
        min_length=30,
        description="How the target/firm performs at this step — strength, weakness, parity.",
    )
    competitive_implication: str = Field(
        ...,
        min_length=10,
        description="So-what: how this assessment shapes the strategic call.",
    )
    evidence_citations: list[str] = Field(
        ...,
        min_length=1,
        description="claim_id strings backing the assessment.",
    )

    model_config = {"extra": "ignore"}


class ValueChainAnalysis(BaseModel):
    business_context: str = Field(
        ...,
        min_length=20,
        description="Scope of the value chain — which business unit / geography / segment.",
    )
    activities: list[ValueChainActivity] = Field(
        ...,
        min_length=4,
        description="At least four activities. A value chain with three steps isn't one.",
    )
    overall_thesis: str = Field(
        ...,
        min_length=30,
        description="Synthesis across activities — where the firm wins / loses / must invest.",
    )

    model_config = {"extra": "ignore"}
