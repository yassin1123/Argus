"""Porter's Five Forces framework payload — W8/D3.

Five-force industry attractiveness analysis. Each force gets the same
shape (:class:`ForceAssessment`) so the renderer can iterate over a
flat list of {force_name, assessment} pairs.

Schema discipline:
- ``market_definition`` is required — the five-forces analysis is
  meaningless without saying what scope "this market" covers (DACH
  industrial services, UK premium grocery, etc.).
- Every force needs 2-6 ``key_drivers`` and ≥1 ``evidence_citations``.
- ``overall_attractiveness`` summary is required so a reader can
  scan the headline without parsing each force.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ForceIntensity = Literal["low", "moderate", "high"]


class ForceAssessment(BaseModel):
    intensity: ForceIntensity = Field(..., description="Strength of this force in the defined market.")
    rationale: str = Field(
        ...,
        min_length=30,
        description="Why this intensity — quantified where possible (concentration ratios, switching costs, etc.).",
    )
    key_drivers: list[str] = Field(
        ...,
        min_length=2,
        max_length=6,
        description="Top 2-6 levers that move this force — chip-rendered in the UI.",
    )
    evidence_citations: list[str] = Field(
        ...,
        min_length=1,
        description="claim_id strings from analysis.key_claims supporting the assessment.",
    )

    model_config = {"extra": "ignore"}


class PortersFiveForcesAnalysis(BaseModel):
    market_definition: str = Field(
        ...,
        min_length=10,
        description="What 'this market' means for the assessment — region, segment, customer type.",
    )
    rivalry: ForceAssessment
    supplier_power: ForceAssessment
    buyer_power: ForceAssessment
    substitute_threat: ForceAssessment
    new_entrant_threat: ForceAssessment
    overall_attractiveness: ForceIntensity = Field(
        ...,
        description="Rollup of the five forces. Same Literal scale; renderer surfaces as a header badge.",
    )
    overall_rationale: str = Field(
        ...,
        min_length=30,
        description="Synthesis explaining the rollup — which forces dominate, which offset.",
    )

    model_config = {"extra": "ignore"}
