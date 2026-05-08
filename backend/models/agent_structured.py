"""Pydantic shapes for structured LLM outputs (analyst, critic, verifier)."""

from __future__ import annotations

import json
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    # Models intermittently emit assumptions as a list of dicts
    # (``[{"assumption": "..."}]``) instead of plain strings; that used
    # to trip the structured-output validator and force a retry. The
    # ``before`` validator coerces dicts to strings so a single typo
    # doesn't blow up the whole analysis. Schema stays narrow:
    # list[str | dict[str, Any]] — the dict path is an escape valve, not
    # the preferred shape (the prompt also tells the model not to wrap).
    assumptions: list[Union[str, dict[str, Any]]] = Field(default_factory=list)

    @field_validator("assumptions", mode="before")
    @classmethod
    def _coerce_assumptions(cls, v: object) -> list[Any]:
        if v is None:
            return []
        if not isinstance(v, list):
            return [str(v).strip()] if str(v).strip() else []
        out: list[Any] = []
        for item in v:
            if isinstance(item, str):
                s = item.strip()
                if s:
                    out.append(s)
            elif isinstance(item, dict):
                # Common shape: {"assumption": "X"} — pull X directly.
                if len(item) == 1 and "assumption" in item:
                    s = str(item["assumption"]).strip()
                    if s:
                        out.append(s)
                # Slightly less common: {"assumption": "X", "rationale": "Y"}
                # Concatenate so neither half is lost.
                elif "assumption" in item:
                    a = str(item.get("assumption") or "").strip()
                    extras = " | ".join(
                        f"{k}: {v}"
                        for k, v in item.items()
                        if k != "assumption" and str(v).strip()
                    )
                    if a:
                        out.append(f"{a} ({extras})" if extras else a)
                else:
                    # No 'assumption' key — best effort: serialise so the
                    # data isn't lost, but the consumer will see noise.
                    try:
                        out.append(json.dumps(item, ensure_ascii=False))
                    except Exception:
                        out.append(str(item))
            else:
                s = str(item).strip()
                if s:
                    out.append(s)
        return out


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
