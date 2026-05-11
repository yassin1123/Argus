"""MAndADiligenceReportPayload — the M&A diligence writer schema.

Strict by design. The seven top-level sections are M&A-specific so a
market-entry pipeline cannot produce an M&A memo by accident:

- target_overview     — what we are buying
- financial_profile   — the historical numbers + their quality
- synergy_estimate    — revenue + cost + dis-synergies, with citations
- risks_and_mitigations
- integration_plan    — day one, first 100 days, first year
- valuation_range     — low / base / high with explicit methodology
- deal_structure_implications — recommended structure + walk-aways

Citation discipline is enforced at the schema level. Every Synergy
must carry at least one ``basis_citations`` entry; every
``ValuationPoint`` must declare a ``methodology``. If the LLM produces
a synergy without a basis citation, validation fails and the writer
retries.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ._base import WriterReportBase


# ---------------------------------------------------------------------------
# 1. TargetOverview
# ---------------------------------------------------------------------------


class Segment(BaseModel):
    name: str = Field(..., description="Segment label (e.g. 'Premium grocery', 'Online D2C').")
    revenue_pct: float = Field(..., ge=0.0, le=100.0, description="Share of total revenue, 0-100.")
    growth_rate: str = Field(..., description="LFL or YoY growth, e.g. '+2.8%' or '-3.4%'.")

    model_config = {"extra": "ignore"}


class GeographyExposure(BaseModel):
    geography: str = Field(..., description="Country or region (e.g. 'UK', 'DACH').")
    revenue_pct: float = Field(..., ge=0.0, le=100.0)

    model_config = {"extra": "ignore"}


class TargetOverview(BaseModel):
    name: str = Field(..., description="Legal or commercial name of the target.")
    business_model: str = Field(..., description="One-paragraph description of how it makes money.")
    segments: list[Segment] = Field(..., min_length=1)
    geographies: list[GeographyExposure] = Field(default_factory=list)
    ownership_history: str = Field(..., description="Founder-owned, PE-backed, listed, family trust, etc.")
    key_customers_concentration: str = Field(..., description="Top-N concentration (e.g. 'top 10 = 38% of revenue').")

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# 2. FinancialProfile
# ---------------------------------------------------------------------------


class TrajectoryPoint(BaseModel):
    period: str = Field(..., description="Period label, e.g. 'FY22' / 'FY23' / 'FY24' / 'LTM'.")
    value_gbp_m: float = Field(..., description="Reported value in £m for this period.")
    growth_rate: str | None = Field(None, description="YoY growth at this period, e.g. '+8.4%'.")
    source_citation: str = Field(..., description="Audit source / file id this value is drawn from.")

    model_config = {"extra": "ignore"}


class RevenueTrajectory(BaseModel):
    points: list[TrajectoryPoint] = Field(..., min_length=2)
    notes: str = Field("", description="Caveats, restatements, FX adjustments, etc.")

    model_config = {"extra": "ignore"}


class EBITDATrajectory(BaseModel):
    points: list[TrajectoryPoint] = Field(..., min_length=2)
    notes: str = Field("", description="Adjusted vs reported EBITDA reconciliation notes.")

    model_config = {"extra": "ignore"}


class MarginProfile(BaseModel):
    gross_margin: str = Field(..., description="Latest period gross margin, e.g. '36.4%'.")
    ebitda_margin: str = Field(..., description="Latest period EBITDA margin.")
    fcf_margin: str = Field(..., description="Latest period FCF margin.")
    trend_commentary: str = Field("", description="2-3 line trend read across periods.")

    model_config = {"extra": "ignore"}


class FinancialProfile(BaseModel):
    revenue_trajectory: RevenueTrajectory
    ebitda_trajectory: EBITDATrajectory
    margin_profile: MarginProfile
    working_capital_dynamics: str = Field(..., description="Days of WC, seasonality, supplier-funded vs customer-funded.")
    debt_structure: str = Field(..., description="Net debt / leverage / covenants / maturities.")
    capex_intensity: str = Field(..., description="Maintenance vs growth capex; capex/revenue %.")
    cash_flow_quality: str = Field(..., description="Recurring vs one-off cash flow shape.")

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# 3. SynergyEstimate
# ---------------------------------------------------------------------------


class Synergy(BaseModel):
    # W8/D2: ``type`` is the natural-language label compared across
    # parent synergy lists (revenue / cost / dis_synergies). Spec
    # called the field ``description`` but the actual schema uses
    # ``type`` for the human-readable text; same intent.
    type: str = Field(
        ...,
        description="Short label, e.g. 'procurement consolidation' or 'cross-sell to legacy book'.",
        json_schema_extra={"mece_check_within_parent_list": True},
    )
    magnitude_gbp_m: float = Field(..., description="Annual run-rate synergy in £m at full realization.")
    timing_months: int = Field(..., ge=0, description="Months from close to full realization.")
    confidence: Literal["high", "medium", "low"] = Field(
        ..., description="Confidence the synergy is realisable at this magnitude."
    )
    basis_citations: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Evidence trace: each entry is a claim_id, source citation, "
            "or document reference that supports the magnitude estimate. "
            "Required and non-empty — schema rejects any synergy without "
            "a defensible basis."
        ),
    )

    model_config = {"extra": "ignore"}

    @field_validator("basis_citations")
    @classmethod
    def _at_least_one_non_blank(cls, v: list[str]) -> list[str]:
        cleaned = [str(x).strip() for x in v if str(x).strip()]
        if not cleaned:
            raise ValueError("basis_citations must contain at least one non-blank entry")
        return cleaned


class NPVRange(BaseModel):
    low_gbp_m: float = Field(..., description="NPV in £m under conservative assumptions.")
    base_gbp_m: float = Field(..., description="NPV in £m under base-case assumptions.")
    high_gbp_m: float = Field(..., description="NPV in £m under aggressive assumptions.")
    discount_rate_pct: float = Field(..., description="WACC used to discount synergy cash flows, e.g. 11.5.")

    model_config = {"extra": "ignore"}


class SynergyEstimate(BaseModel):
    revenue_synergies: list[Synergy] = Field(default_factory=list)
    cost_synergies: list[Synergy] = Field(default_factory=list)
    dis_synergies: list[Synergy] = Field(
        default_factory=list,
        description=(
            "The negative side of the deal — customer attrition, talent "
            "loss, integration friction, transition cost run-rate. "
            "Under-budgeting these is the single most common way M&A "
            "deals destroy value, so the schema makes the section "
            "first-class even when the LLM would prefer to omit it."
        ),
    )
    net_present_value: NPVRange
    realization_timeline: str = Field(
        ..., description="Narrative on the year-by-year realization curve."
    )

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# 4. RiskAssessment
# ---------------------------------------------------------------------------


class RiskAssessment(BaseModel):
    risk_category: Literal[
        "commercial", "operational", "financial", "legal", "regulatory"
    ] = Field(..., description="Top-level risk taxonomy bucket.")
    # W8/D2: risk descriptions across risks_and_mitigations[] should be
    # MECE — overlap means two risks are really one. Compared within
    # the parent list.
    description: str = Field(
        ...,
        description="One-paragraph risk statement.",
        json_schema_extra={"mece_check_within_parent_list": True},
    )
    severity: Literal["high", "medium", "low"]
    mitigation: str = Field(..., description="How the buyer plans to manage the risk pre- or post-close.")
    residual_risk: str = Field(
        ..., description="What remains after mitigation; honest assessment, not optimistic."
    )

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# 5. IntegrationPlan
# ---------------------------------------------------------------------------


class InitiativeBlock(BaseModel):
    workstream: str = Field(..., description="Workstream name, e.g. 'IT integration', 'GTM consolidation'.")
    owner_role: str = Field(..., description="Role title accountable, e.g. 'CTO', 'Head of Integration Office'.")
    milestone: str = Field(..., description="Concrete, observable milestone for this block.")
    dependencies: list[str] = Field(default_factory=list, description="Other blocks or external events this depends on.")

    model_config = {"extra": "ignore"}


class IntegrationPlan(BaseModel):
    day_one_priorities: list[str] = Field(
        ...,
        min_length=1,
        description="What must be working on legal close day; e.g. 'payroll continuity', 'customer comms sent'.",
    )
    first_100_days: list[InitiativeBlock] = Field(..., min_length=1)
    first_year: list[InitiativeBlock] = Field(default_factory=list)
    integration_complexity_rating: Literal["low", "medium", "high"]
    complexity_rationale: str = Field(
        ..., description="Why this complexity rating; ties back to system overlap, geography, culture, regulatory."
    )

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# 6. ValuationRange
# ---------------------------------------------------------------------------


class ValuationPoint(BaseModel):
    gbp_m: float = Field(..., description="Enterprise value in £m at this scenario.")
    methodology: str = Field(
        ...,
        min_length=1,
        description=(
            "Required: which valuation method drove this point — "
            "'DCF @ WACC 11%', 'EV/EBITDA 8.5x precedent', "
            "'EV/Sales 1.4x trading comps', etc. Empty methodology fails "
            "validation; we do not let an LLM hand back a number without "
            "saying how it got there."
        ),
    )
    key_assumptions: list[str] = Field(
        default_factory=list,
        description="2-4 anchoring assumptions (e.g. 'terminal growth 2.5%', 'WC days flat at 51').",
    )

    model_config = {"extra": "ignore"}

    @field_validator("methodology")
    @classmethod
    def _methodology_non_blank(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("ValuationPoint.methodology must be a non-blank explanation")
        return v


class ComparableTransaction(BaseModel):
    target: str = Field(..., description="Target company name in the comparable.")
    acquirer: str = Field(..., description="Acquirer company name.")
    year: int = Field(..., ge=1990, le=2100, description="Announcement year.")
    multiple: str = Field(..., description="Multiple cited, e.g. '9.2x EV/EBITDA' or '1.6x EV/Sales'.")
    source_citation: str = Field(..., description="Source for the multiple (deal database, press release, filing).")

    model_config = {"extra": "ignore"}


class ValuationRange(BaseModel):
    low: ValuationPoint
    base: ValuationPoint
    high: ValuationPoint
    multiples_implied: dict[str, float] = Field(
        ...,
        description=(
            "Multiples at the BASE case. Must include 'EV/EBITDA' and "
            "'EV/Sales' at minimum; additional bespoke multiples optional."
        ),
    )
    comparable_transactions_cited: list[ComparableTransaction] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @field_validator("multiples_implied")
    @classmethod
    def _required_multiples_present(cls, v: dict[str, float]) -> dict[str, float]:
        keys_lower = {k.lower() for k in v.keys()}
        if "ev/ebitda" not in keys_lower or "ev/sales" not in keys_lower:
            raise ValueError(
                "multiples_implied must include both 'EV/EBITDA' and 'EV/Sales' at base case"
            )
        return v


# ---------------------------------------------------------------------------
# 7. DealStructureImplications
# ---------------------------------------------------------------------------


class DealStructureImplications(BaseModel):
    recommended_structure: str = Field(
        ...,
        description=(
            "Asset vs share, cash vs mixed, earn-out shape — one paragraph."
        ),
    )
    rationale: str = Field(..., description="Why this structure given target shape, sponsor goals, tax treatment.")
    # W8/D2: negotiation_priorities and walk_away_triggers are
    # high-signal MECE candidates — duplicate priorities or triggers
    # signal the writer is hedging instead of picking sharp bright
    # lines.
    negotiation_priorities: list[str] = Field(
        ...,
        min_length=1,
        description="Top 3-6 asks the buyer should hold the line on at the table.",
        json_schema_extra={"mece_check": True},
    )
    walk_away_triggers: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Falsifiable conditions under which the deal stops. Each item "
            "should read like 'If <observation> at <gate>, walk.' These "
            "are the bright lines that make the recommendation honest."
        ),
        json_schema_extra={"mece_check": True},
    )

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Top-level payload
# ---------------------------------------------------------------------------


class MAndADiligenceReportPayload(WriterReportBase):
    """Full M&A diligence memo. Inherits the base recommendation/summary
    /citation/etc. fields and adds seven mode-specific structured
    sections that a market-entry or growth-strategy pipeline can't
    plausibly produce by accident.
    """

    mode: Literal["m_and_a_diligence"] = "m_and_a_diligence"

    target_overview: TargetOverview
    financial_profile: FinancialProfile
    synergy_estimate: SynergyEstimate
    risks_and_mitigations: list[RiskAssessment] = Field(..., min_length=1)
    integration_plan: IntegrationPlan
    valuation_range: ValuationRange
    deal_structure_implications: DealStructureImplications

    def consulting_payload_dict(self) -> dict[str, object]:
        """Extend the base serialiser with the M&A-specific sections so
        the persisted ``reports.consulting_payload`` carries them too.
        Down-stream consumers (export, UI) read either the base fields
        or these — both are durable in JSONB.
        """
        base = super().consulting_payload_dict()
        base.update(
            {
                "target_overview": self.target_overview.model_dump(),
                "financial_profile": self.financial_profile.model_dump(),
                "synergy_estimate": self.synergy_estimate.model_dump(),
                "risks_and_mitigations": [r.model_dump() for r in self.risks_and_mitigations],
                "integration_plan": self.integration_plan.model_dump(),
                "valuation_range": self.valuation_range.model_dump(),
                "deal_structure_implications": self.deal_structure_implications.model_dump(),
            }
        )
        return base
