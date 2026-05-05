"""Structured reasoning graph (persisted as JSONB) — not a second evidence schema."""

from typing import Any

from pydantic import BaseModel, Field


class ReasoningClaim(BaseModel):
    claim_id: str = ""
    text: str = ""
    evidence_object_ids: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class ReasoningAssumption(BaseModel):
    text: str = ""
    evidence_object_ids: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class ReasoningCriterion(BaseModel):
    name: str = ""
    weight: str = "medium"
    notes: str = ""

    model_config = {"extra": "ignore"}


class ReasoningRisk(BaseModel):
    text: str = ""
    severity: str = "medium"

    model_config = {"extra": "ignore"}


class Hypothesis(BaseModel):
    id: str = ""
    text: str = ""
    evidence_object_ids: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class CounterEvidenceItem(BaseModel):
    id: str = ""
    text: str = ""
    evidence_object_ids: list[str] = Field(default_factory=list)
    source: str = ""

    model_config = {"extra": "ignore"}


class ReasoningGraph(BaseModel):
    """Snapshot derived from analyst JSON for writer/exports."""

    recommendation: str = ""
    confidence: str = ""
    core_reasoning: str = ""
    reasoning_slots: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[ReasoningClaim] = Field(default_factory=list)
    assumptions: list[ReasoningAssumption] = Field(default_factory=list)
    criteria: list[ReasoningCriterion] = Field(default_factory=list)
    risks: list[ReasoningRisk] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    counter_evidence: list[CounterEvidenceItem] = Field(default_factory=list)
    evidence_strength: str = ""

    model_config = {"extra": "ignore"}

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def build_reasoning_graph(analysis: dict[str, Any]) -> ReasoningGraph:
    from core.reasoning_skeleton import normalize_reasoning_slots_for_graph

    slot_rows = normalize_reasoning_slots_for_graph(analysis)
    claims: list[ReasoningClaim] = []
    kc = analysis.get("key_claims")
    if isinstance(kc, list):
        for i, item in enumerate(kc):
            if not isinstance(item, dict):
                continue
            raw = item.get("evidence_ids")
            eids = [str(x) for x in raw] if isinstance(raw, list) else []
            cid = str(item.get("claim_id") or "").strip() or f"kc_{i}"
            claims.append(
                ReasoningClaim(
                    claim_id=cid,
                    text=str(item.get("text", ""))[:2000],
                    evidence_object_ids=eids,
                )
            )
    assumptions: list[ReasoningAssumption] = []
    for i, a in enumerate(analysis.get("assumptions") or []):
        if isinstance(a, str) and a.strip():
            assumptions.append(ReasoningAssumption(text=a.strip()[:2000]))
        elif isinstance(a, dict):
            assumptions.append(
                ReasoningAssumption(
                    text=str(a.get("text", ""))[:2000],
                    evidence_object_ids=[str(x) for x in a.get("evidence_ids", [])]
                    if isinstance(a.get("evidence_ids"), list)
                    else [],
                )
            )
    criteria: list[ReasoningCriterion] = []
    for c in analysis.get("trade_offs") or []:
        if isinstance(c, dict):
            criteria.append(
                ReasoningCriterion(
                    name=str(c.get("option", ""))[:500],
                    notes=str(c.get("pros", ""))[:500] + " / " + str(c.get("cons", ""))[:500],
                )
            )
    risks: list[ReasoningRisk] = []
    for r in analysis.get("risks") or []:
        if isinstance(r, str):
            risks.append(ReasoningRisk(text=r[:2000]))
    return ReasoningGraph(
        recommendation=str(analysis.get("recommendation", ""))[:4000],
        confidence=str(analysis.get("confidence", "")),
        core_reasoning=str(analysis.get("core_reasoning", ""))[:8000],
        reasoning_slots=slot_rows,
        claims=claims,
        assumptions=assumptions,
        criteria=criteria,
        risks=risks,
        evidence_strength=str(analysis.get("evidence_strength", ""))[:2000],
    )


def merge_verifier_and_research_into_graph(
    graph_dict: dict[str, Any],
    verification: dict[str, Any],
    research_contradictions: list[str],
) -> None:
    """Augment persisted reasoning_graph with hypotheses and counter-evidence (mutates dict)."""
    claims = graph_dict.get("claims") if isinstance(graph_dict.get("claims"), list) else []
    union_ids: list[str] = []
    for c in claims:
        if isinstance(c, dict):
            for x in c.get("evidence_object_ids") or []:
                s = str(x)
                if s and s not in union_ids:
                    union_ids.append(s)
    rec = str(graph_dict.get("recommendation") or "")[:900]
    graph_dict["hypotheses"] = [
        {
            "id": "h_main",
            "text": rec or str(graph_dict.get("core_reasoning") or "")[:900],
            "evidence_object_ids": union_ids[:24],
        }
    ]
    ce: list[dict[str, Any]] = []
    for i, x in enumerate(verification.get("contradictions") or []):
        if isinstance(x, str) and x.strip():
            ce.append(
                {
                    "id": f"ver_{i}",
                    "text": x.strip()[:1500],
                    "evidence_object_ids": [],
                    "source": "verifier",
                }
            )
    for i, x in enumerate(research_contradictions or []):
        if isinstance(x, str) and x.strip():
            ce.append(
                {
                    "id": f"res_{i}",
                    "text": x.strip()[:1500],
                    "evidence_object_ids": [],
                    "source": "research_tension",
                }
            )
    graph_dict["counter_evidence"] = ce[:12]
