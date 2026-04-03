"""TrustObject shape persisted in session metadata (labels + counts)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TrustObject(BaseModel):
    confidence_level: str = ""
    confidence_display: str = ""
    evidence_strength_label: str = ""
    verification_overall_label: str = ""
    contradiction_severity_label: str = ""
    unsupported_claims_count: int = 0
    what_capped_confidence: str = ""
    claims_verified_hint: str = ""

    model_config = {"extra": "ignore"}
