"""Pydantic shapes for structured LLM outputs (analyst, critic, verifier)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnalystKeyClaim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim_id: str | None = None
    text: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class AnalystReasoningSlot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot_id: str = ""
    summary: str = ""
    claim_ids: list[str] = Field(default_factory=list)


class AnalystTradeOff(BaseModel):
    model_config = ConfigDict(extra="ignore")

    option: str = ""
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class AnalystStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recommendation: str = ""
    confidence: str = "Medium"
    core_reasoning: str = ""
    key_reasons: list[str] = Field(default_factory=list)
    key_claims: list[AnalystKeyClaim] = Field(default_factory=list)
    reasoning_slots: list[AnalystReasoningSlot] = Field(default_factory=list)
    trade_offs: list[AnalystTradeOff] = Field(default_factory=list)
    evidence_strength: str = ""
    assumptions: list[str] = Field(default_factory=list)


class RevisionInstruction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target: str = "key_claims"
    severity: str = "medium"
    instruction: str = ""


class CriticStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    overall_assessment: str = ""
    revision_instructions: list[RevisionInstruction] = Field(default_factory=list)
    weak_points: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    risks_missed: list[str] = Field(default_factory=list)
    confidence_adjustment: str = ""
    verdict: str = "accept"


class ClaimAssessment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    verdict: str = "weak"
    notes: str = ""


class VerifierStructuredOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claim_assessments: list[ClaimAssessment] = Field(default_factory=list)
    overall: str = "insufficient"
    gap_summary: str = ""
    suggested_searches: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
