from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceItem(BaseModel):
    title: str
    type: str

    model_config = {"extra": "ignore"}


class ExecutiveInsightItem(BaseModel):
    text: str = ""
    claim_ids: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class KeyRiskStructuredItem(BaseModel):
    text: str = ""
    claim_ids: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class WriterReportPayload(BaseModel):
    """Writer JSON mapped to `reports` table + consulting_payload JSONB."""

    recommendation: str
    confidence_level: str
    summary: str
    key_reasons: list[str]
    risks: list[str]
    counterarguments: list[str]
    next_steps: list[str]
    sources: list[SourceItem]
    caveats: str = ""
    executive_insights: list[ExecutiveInsightItem] = Field(default_factory=list)
    recommendation_claim_ids: list[str] = Field(default_factory=list)
    key_risks_structured: list[KeyRiskStructuredItem] = Field(default_factory=list)
    decision_criteria: list[Any] = Field(default_factory=list)
    options_matrix: list[Any] = Field(default_factory=list)
    kill_criteria: list[str] = Field(default_factory=list)
    what_would_change_our_mind: str = ""
    evidence_ledger_summary: str = ""

    model_config = {"extra": "ignore"}

    @field_validator("key_reasons", "risks", "counterarguments", "next_steps", "kill_criteria", mode="before")
    @classmethod
    def ensure_str_lists(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)]

    @field_validator("executive_insights", mode="before")
    @classmethod
    def coerce_executive_insights(cls, v: Any) -> list[Any]:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        out: list[dict[str, Any]] = []
        for item in v:
            if isinstance(item, dict):
                cids = item.get("claim_ids")
                if not isinstance(cids, list):
                    cids = []
                out.append(
                    {
                        "text": str(item.get("text", "")),
                        "claim_ids": [str(x).strip() for x in cids if str(x).strip()],
                    }
                )
            elif isinstance(item, str) and item.strip():
                out.append({"text": item.strip(), "claim_ids": []})
        return out

    @field_validator("key_risks_structured", mode="before")
    @classmethod
    def coerce_key_risks_structured(cls, v: Any) -> list[Any]:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        out: list[dict[str, Any]] = []
        for item in v:
            if isinstance(item, dict):
                cids = item.get("claim_ids")
                if not isinstance(cids, list):
                    cids = []
                out.append(
                    {
                        "text": str(item.get("text", "")),
                        "claim_ids": [str(x).strip() for x in cids if str(x).strip()],
                    }
                )
        return out

    @field_validator("recommendation_claim_ids", mode="before")
    @classmethod
    def coerce_recommendation_claim_ids(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    @field_validator("decision_criteria", "options_matrix", mode="before")
    @classmethod
    def ensure_obj_lists(cls, v: Any) -> list[Any]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []

    @model_validator(mode="before")
    @classmethod
    def coerce_sources(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        src = data.get("sources")
        if isinstance(src, list):
            norm: list[dict[str, str]] = []
            for item in src:
                if isinstance(item, dict):
                    norm.append(
                        {
                            "title": str(item.get("title", "Unknown")),
                            "type": str(item.get("type", "knowledge")),
                        }
                    )
                else:
                    norm.append({"title": str(item), "type": "knowledge"})
            data["sources"] = norm
        return data

    def consulting_payload_dict(self) -> dict[str, Any]:
        return {
            "executive_insights": [x.model_dump() for x in self.executive_insights],
            "recommendation_claim_ids": list(self.recommendation_claim_ids),
            "key_risks_structured": [x.model_dump() for x in self.key_risks_structured],
            "decision_criteria": self.decision_criteria,
            "options_matrix": self.options_matrix,
            "kill_criteria": self.kill_criteria,
            "what_would_change_our_mind": self.what_would_change_our_mind,
            "evidence_ledger_summary": self.evidence_ledger_summary,
        }


class ReportRow(BaseModel):
    id: UUID
    session_id: UUID
    recommendation: str
    confidence_level: str
    summary: str
    key_reasons: list[Any]
    risks: list[Any]
    counterarguments: list[Any]
    next_steps: list[Any]
    sources: list[Any]
    raw_output: str | None
    caveats: str
    created_at: datetime
