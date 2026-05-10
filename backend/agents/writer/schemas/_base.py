"""Phase 2 / Week 7 / Day 1 — base writer-payload schema.

Every writer schema in the registry inherits from :class:`WriterReportBase`.
The subclasses (``GeneralReportPayload``, ``MAndADiligenceReportPayload``,
…) add mode-specific fields on top of the shared core.

Spec divergence note (W7/D1):
    The Day-1 spec listed the base fields as
    ``mode / executive_summary / assumptions / claim_citations /
    verification_report_summary / metadata``. The actual pre-W7 codebase
    (``backend/models/report.py``) shipped a different shared field set
    that all four built-in modes already produce — ``recommendation`` /
    ``confidence_level`` / ``summary`` / ``key_reasons`` / ``risks`` /
    ``counterarguments`` / ``next_steps`` / ``sources`` / ``caveats`` /
    ``executive_insights`` / etc.

    Per the hard rule "Don't change GeneralReportPayload's field set",
    we keep the actual existing fields on the base and add ``mode`` +
    ``metadata`` as new optional fields (non-breaking — empty defaults,
    so existing JSON parses unchanged). Spec fields not yet shipped
    (``assumptions``, ``claim_citations``, ``verification_report_summary``)
    can be added later without breaking any subclass; for today the base
    matches what real data flowing through the pipeline carries.
"""

from __future__ import annotations

from typing import Any

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


class WriterReportBase(BaseModel):
    """Shared fields produced by every consulting mode's writer.

    The concrete schemas in ``_general.py`` and ``_m_and_a.py`` extend
    this with mode-specific extras. ``mode`` is the literal slug the
    registry uses to route — subclasses override it with a
    ``Literal[...]`` so a payload's mode is self-describing.
    """

    mode: str = Field("general", description="Consulting mode slug this payload was produced under.")

    recommendation: str = Field(..., description="One-sentence specific recommendation naming the chosen option.")
    confidence_level: str = Field(..., description="Low | Medium | Medium-High | High.")
    summary: str = Field(..., description="2-4 sentence executive summary; no new facts beyond linked claims.")
    key_reasons: list[str] = Field(..., description="4-7 evidence-cited reasons supporting the recommendation.")
    risks: list[str] = Field(..., description="Material risks the recommendation must survive.")
    counterarguments: list[str] = Field(..., description="Critic's strongest counterarguments + responses.")
    next_steps: list[str] = Field(..., description="5-9 time-bound, action-verb steps.")
    sources: list[SourceItem] = Field(..., description="Sources cited; each {title, type}.")
    caveats: str = Field("", description="Limitations of this analysis.")
    executive_insights: list[ExecutiveInsightItem] = Field(default_factory=list)
    recommendation_claim_ids: list[str] = Field(default_factory=list)
    key_risks_structured: list[KeyRiskStructuredItem] = Field(default_factory=list)
    decision_criteria: list[Any] = Field(default_factory=list)
    options_matrix: list[Any] = Field(default_factory=list)
    kill_criteria: list[str] = Field(default_factory=list)
    what_would_change_our_mind: str = Field("", description="Concrete thresholds that would shift the view.")
    evidence_ledger_summary: str = Field("", description="One-paragraph honesty check on evidence depth.")

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Free-form bag for forward-compatible per-mode hints we "
            "haven't promoted to first-class fields yet."
        ),
    )

    model_config = {"extra": "ignore"}

    # Coercion validators — ported from the legacy WriterReportPayload so
    # the same forgiving inputs that worked on V2 continue to parse on V3.
    # The LLM occasionally hands back stringy variants of these list shapes;
    # we soak that up rather than fail validation outright.

    @field_validator(
        "key_reasons", "risks", "counterarguments", "next_steps", "kill_criteria",
        mode="before",
    )
    @classmethod
    def _ensure_str_lists(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v]
        return [str(v)]

    @field_validator("executive_insights", mode="before")
    @classmethod
    def _coerce_executive_insights(cls, v: Any) -> list[Any]:
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
    def _coerce_key_risks_structured(cls, v: Any) -> list[Any]:
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
    def _coerce_recommendation_claim_ids(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    @field_validator("decision_criteria", "options_matrix", mode="before")
    @classmethod
    def _ensure_obj_lists(cls, v: Any) -> list[Any]:
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return []

    @model_validator(mode="before")
    @classmethod
    def _coerce_sources(cls, data: Any) -> Any:
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
        """Subset persisted to ``reports.consulting_payload`` JSONB.

        Subclasses with extra mode-specific fields can override this to
        also serialise their own structured sections.
        """
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
