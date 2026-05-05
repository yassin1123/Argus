"""Structured deliverable (presentation layer) — built from persisted report rows."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class FindingBlock(BaseModel):
    title: str = ""
    explanation: str = ""
    evidence_refs: str = ""
    mini_conclusion: str = ""

    model_config = {"extra": "ignore"}


class CriteriaRow(BaseModel):
    criterion: str = ""
    score: str = ""
    notes: str = ""

    model_config = {"extra": "ignore"}


class ClaimMapRow(BaseModel):
    claim: str = ""
    evidence: str = ""

    model_config = {"extra": "ignore"}


class DeliverableDocument(BaseModel):
    cover_title: str = "Argus Decision Deliverable"
    cover_subtitle: str = ""
    cover_date: str = ""
    cover_project: str = ""
    exec_insights: list[str] = Field(default_factory=list)
    exec_recommendation: str = ""
    exec_risks: list[str] = Field(default_factory=list)
    key_question: str = ""
    findings: list[FindingBlock] = Field(default_factory=list)
    criteria_rows: list[CriteriaRow] = Field(default_factory=list)
    recommendation_body: str = ""
    risks_body: list[str] = Field(default_factory=list)
    appendix_sources: list[str] = Field(default_factory=list)
    appendix_claim_map: list[ClaimMapRow] = Field(default_factory=list)
    caveats: str = ""

    model_config = {"extra": "ignore"}

    @classmethod
    def default_date(cls) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
