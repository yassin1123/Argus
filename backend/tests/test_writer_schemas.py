"""Phase 2 / Week 7 / Day 1 — schema registry + M&A diligence payload tests.

Hermetic: no DB, no LLM. Validates Pydantic shape only.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.writer.schemas import (
    GeneralReportPayload,
    MAndADiligenceReportPayload,
    WriterReportBase,
    get_writer_schema,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _general_payload_json() -> dict:
    """Mimics the exact shape pre-W7 writer outputs land in. Used by
    test_general_payload_unchanged_from_legacy as a regression
    fixture — if this stops parsing, the W7 refactor broke real
    engagement data."""
    return {
        "recommendation": "Enter Germany first via a 6-month Mittelstand pilot in NRW + Bavaria",
        "confidence_level": "Medium-High",
        "summary": "Germany pilot first; €4.2m incremental ARR base case; biggest risk is procurement cycle length, gated by month-5 LOI count.",
        "key_reasons": [
            "Concentrates 41% of TAM in NRW + Bavaria per study Y2024.",
            "Cuts procurement cycle by 2.4 months vs France baseline.",
        ],
        "risks": ["Procurement cycle could exceed 9 months at scale."],
        "counterarguments": ["France first lets us reuse the Paris GTM team; rebutted by procurement-cycle delta."],
        "next_steps": [
            "This week: Recruit Germany country lead.",
            "Within 30 days: Sign 3 anchor LOIs in Munich.",
            "Within 90 days: Stand up DACH ops shell.",
            "By month 6: Validate procurement cycle median <= 6.5 months.",
            "Month 5: review 6-anchor pipeline; if 0 LOIs, kill phase-2 plan.",
        ],
        "sources": [
            {"title": "GfK DACH market study 2024", "type": "knowledge"},
            {"title": "Internal procurement cycle data", "type": "document"},
        ],
        "caveats": "Procurement cycle estimates from 2 customer references only.",
        "executive_insights": [
            {"text": "NRW + Bavaria carry 41% of TAM.", "claim_ids": ["c1"]},
        ],
        "recommendation_claim_ids": ["c1", "c2"],
        "key_risks_structured": [
            {"text": "9-month procurement cycle risk", "claim_ids": ["c3"]},
        ],
        "decision_criteria": [
            {"criterion": "Time to first revenue", "weight": "high", "how_met": "<=6 months", "evidence_ids": ["c1"]},
        ],
        "options_matrix": [
            {"option": "Germany first", "fit": "Best at this team size", "pros": ["TAM density"], "cons": ["FX hedging"]},
        ],
        "kill_criteria": ["If 0 of 6 anchors move to LOI by month 5, halt phase 2."],
        "what_would_change_our_mind": "Direct evidence French procurement cycles are <= German.",
        "evidence_ledger_summary": "GfK study + internal procurement data; n=2 internal references.",
    }


def _ma_payload_json(**overrides) -> dict:
    """Hand-written M&A payload covering all 7 sections. Tests override
    specific fields to drive validation failures."""
    base = {
        "recommendation": "Acquire Albright & Marsh Group at £210m EV with 70% cash / 30% rolled equity, gated by management retention.",
        "confidence_level": "Medium-High",
        "summary": "Acquire Albright & Marsh at £210m EV; £18m run-rate cost synergies in 18 months; biggest risk is Home segment turn-around dependency, mitigated by month-9 LFL gate.",
        "key_reasons": [
            "Premium segment 71.8% retention with -0.8 elasticity supports 5.5% pricing headroom.",
            "Discounter pair has 8% Food index headroom available for defensive repricing.",
        ],
        "risks": ["Home segment LFL recovery is unproven."],
        "counterarguments": ["Sponsor exit window of 24 months may be too tight; rebutted by 18-month synergy realization plan."],
        "next_steps": [
            "This week: Sign LOI at £210m headline.",
            "Within 30 days: Complete management retention term sheets.",
            "Within 90 days: Validate Home segment turn-around in week-12 LFL read.",
            "By month 6: Lock supplier-side renegotiation deltas.",
            "Month 9: review Home LFL; if <-1.5%, slow Home capex.",
        ],
        "sources": [
            {"title": "Albright Pricing Diagnostic Pack", "type": "document"},
        ],
        "caveats": "Synergy estimates depend on supplier-side renegotiation outcomes.",
        "target_overview": {
            "name": "Albright & Marsh Group",
            "business_model": "UK multi-segment retailer across Food, Premium, Home, Online; 142-store estate plus D2C marketplace.",
            "segments": [
                {"name": "Food", "revenue_pct": 50.4, "growth_rate": "+1.4%"},
                {"name": "Premium", "revenue_pct": 19.1, "growth_rate": "+2.8%"},
                {"name": "Home", "revenue_pct": 18.5, "growth_rate": "-3.4%"},
                {"name": "Online", "revenue_pct": 12.0, "growth_rate": "+6.8%"},
            ],
            "geographies": [{"geography": "UK", "revenue_pct": 100.0}],
            "ownership_history": "Marylebone Equity sponsor-owned, vintage 2020; 24-month exit window.",
            "key_customers_concentration": "Retail B2C; no top-customer concentration risk.",
        },
        "financial_profile": {
            "revenue_trajectory": {
                "points": [
                    {"period": "FY22", "value_gbp_m": 188.0, "growth_rate": "+1.2%", "source_citation": "Albright Pricing Pack p.2"},
                    {"period": "FY24", "value_gbp_m": 203.0, "growth_rate": "+2.1%", "source_citation": "Albright Pricing Pack p.2"},
                ],
                "notes": "FY24 LFL +2.1% blended.",
            },
            "ebitda_trajectory": {
                "points": [
                    {"period": "FY22", "value_gbp_m": 19.4, "growth_rate": None, "source_citation": "Albright Pricing Pack p.2"},
                    {"period": "FY24", "value_gbp_m": 21.7, "growth_rate": "+5.8%", "source_citation": "Albright Pricing Pack p.2"},
                ],
                "notes": "10.7% margin in FY24.",
            },
            "margin_profile": {
                "gross_margin": "36.4%",
                "ebitda_margin": "10.7%",
                "fcf_margin": "6.2%",
                "trend_commentary": "180bps gross margin erosion FY22-FY24, driven by Food + Home.",
            },
            "working_capital_dynamics": "WC cycle 38d FY22 -> 51d FY24; Food + Home explain 12 of 13 day deterioration.",
            "debt_structure": "Net debt 1.4x EBITDA; bullet maturity FY27.",
            "capex_intensity": "Capex/revenue 2.8% blended; growth capex 1.2%.",
            "cash_flow_quality": "85% recurring, 15% one-off store-rationalisation cash.",
        },
        "synergy_estimate": {
            "revenue_synergies": [
                {
                    "type": "Premium pricing headroom realization",
                    "magnitude_gbp_m": 1.8,
                    "timing_months": 12,
                    "confidence": "medium",
                    "basis_citations": ["Albright WTP study Q4 FY24 p.4", "claim_07"],
                },
            ],
            "cost_synergies": [
                {
                    "type": "Procurement consolidation across portfolio",
                    "magnitude_gbp_m": 12.0,
                    "timing_months": 18,
                    "confidence": "high",
                    "basis_citations": ["Albright Pricing Pack p.5"],
                },
            ],
            "dis_synergies": [
                {
                    "type": "Home segment customer attrition during pricing reset",
                    "magnitude_gbp_m": 2.4,
                    "timing_months": 9,
                    "confidence": "medium",
                    "basis_citations": ["Albright WTP study big-ticket elasticity -2.1"],
                },
            ],
            "net_present_value": {
                "low_gbp_m": 38.0,
                "base_gbp_m": 64.0,
                "high_gbp_m": 92.0,
                "discount_rate_pct": 11.5,
            },
            "realization_timeline": "Year 1: 30% of run-rate; Year 2: 75%; Year 3: 100%.",
        },
        "risks_and_mitigations": [
            {
                "risk_category": "commercial",
                "description": "Home segment -3.4% LFL may not reverse with -9% big-ticket repricing alone.",
                "severity": "high",
                "mitigation": "Week-12 LFL gate; pause Home capex if LFL < -1.5%.",
                "residual_risk": "If pricing alone insufficient, store-network closure ramp may be needed.",
            },
        ],
        "integration_plan": {
            "day_one_priorities": [
                "Payroll continuity",
                "Customer comms sent to top 1000 accounts",
                "ERP read-only access for buyer team",
            ],
            "first_100_days": [
                {
                    "workstream": "Pricing system change",
                    "owner_role": "Pricing Director",
                    "milestone": "Week-6 deployment of segment-specific price changes via SAP S/4HANA",
                    "dependencies": ["Supplier renegotiation alignment", "CFO sign-off"],
                },
            ],
            "first_year": [
                {
                    "workstream": "Home segment turn-around",
                    "owner_role": "Head of Category — Home",
                    "milestone": "LFL inflection from -3.4% to -1.5% by month 9",
                    "dependencies": ["Pricing system change live"],
                },
            ],
            "integration_complexity_rating": "medium",
            "complexity_rationale": "Single ERP and single geography reduce complexity; segment heterogeneity raises it.",
        },
        "valuation_range": {
            "low": {
                "gbp_m": 175.0,
                "methodology": "DCF @ WACC 12% with terminal growth 2.0%; conservative Home assumptions",
                "key_assumptions": ["Home LFL -2% through year 3", "Supplier renegotiation £6m"],
            },
            "base": {
                "gbp_m": 210.0,
                "methodology": "DCF @ WACC 11.5% triangulated against EV/EBITDA 9.7x",
                "key_assumptions": ["Home LFL -1% by year 3", "Supplier renegotiation £12m"],
            },
            "high": {
                "gbp_m": 245.0,
                "methodology": "EV/EBITDA 11.3x precedent transactions in UK mid-market retail FY22-24",
                "key_assumptions": ["Home LFL flat by year 3", "Online expansion to 18% mix"],
            },
            "multiples_implied": {"EV/EBITDA": 9.7, "EV/Sales": 1.04},
            "comparable_transactions_cited": [
                {
                    "target": "WHSmith Travel",
                    "acquirer": "Lagardère Travel Retail",
                    "year": 2023,
                    "multiple": "11.0x EV/EBITDA",
                    "source_citation": "Mergermarket DB (FY23 H2)",
                },
            ],
        },
        "deal_structure_implications": {
            "recommended_structure": "Share purchase, 70% cash + 30% rolled equity from sponsor with 3-year vest; £15m earn-out tied to year-2 EBITDA bridge.",
            "rationale": "Rolled equity aligns sponsor incentives through transition; earn-out shifts risk on Home segment recovery.",
            "negotiation_priorities": [
                "Management retention package locked at LOI",
                "Earn-out trigger above £24m EBITDA at year 2",
                "Working-capital peg at 51 days",
            ],
            "walk_away_triggers": [
                "If Home LFL < -3% in week-12 read, walk on base-case price",
                "If ERP migration estimate exceeds £4m, renegotiate",
            ],
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. test_general_payload_unchanged_from_legacy
# ---------------------------------------------------------------------------


def test_general_payload_unchanged_from_legacy() -> None:
    """Pre-W7 writer JSON must continue to parse cleanly into
    GeneralReportPayload after the schema registry refactor."""
    payload = GeneralReportPayload.model_validate(_general_payload_json())
    assert payload.recommendation.startswith("Enter Germany")
    assert payload.confidence_level == "Medium-High"
    assert len(payload.next_steps) == 5
    assert payload.executive_insights[0].claim_ids == ["c1"]
    assert payload.mode == "general"  # default fills in
    # Helper still emits the consulting_payload subset.
    cp = payload.consulting_payload_dict()
    assert "decision_criteria" in cp


# ---------------------------------------------------------------------------
# 2. test_ma_payload_validates_minimum_shape
# ---------------------------------------------------------------------------


def test_ma_payload_validates_minimum_shape() -> None:
    payload = MAndADiligenceReportPayload.model_validate(_ma_payload_json())
    assert payload.mode == "m_and_a_diligence"
    # All 7 top-level sections present.
    assert payload.target_overview.name == "Albright & Marsh Group"
    assert len(payload.target_overview.segments) == 4
    assert payload.financial_profile.margin_profile.gross_margin == "36.4%"
    assert len(payload.synergy_estimate.cost_synergies) == 1
    assert payload.synergy_estimate.net_present_value.base_gbp_m == 64.0
    assert payload.risks_and_mitigations[0].severity == "high"
    assert payload.integration_plan.integration_complexity_rating == "medium"
    assert payload.valuation_range.base.gbp_m == 210.0
    assert payload.deal_structure_implications.walk_away_triggers
    # consulting_payload extension carries the M&A sections.
    cp = payload.consulting_payload_dict()
    assert "synergy_estimate" in cp
    assert "valuation_range" in cp


# ---------------------------------------------------------------------------
# 3. test_ma_payload_rejects_missing_valuation_methodology
# ---------------------------------------------------------------------------


def test_ma_payload_rejects_missing_valuation_methodology() -> None:
    bad = _ma_payload_json()
    # Drop methodology from the base case.
    bad["valuation_range"]["base"]["methodology"] = ""
    with pytest.raises(ValidationError) as exc:
        MAndADiligenceReportPayload.model_validate(bad)
    assert "methodology" in str(exc.value)


# ---------------------------------------------------------------------------
# 4. test_ma_payload_rejects_missing_synergy_basis_citations
# ---------------------------------------------------------------------------


def test_ma_payload_rejects_missing_synergy_basis_citations() -> None:
    bad = _ma_payload_json()
    bad["synergy_estimate"]["cost_synergies"][0]["basis_citations"] = []
    with pytest.raises(ValidationError) as exc:
        MAndADiligenceReportPayload.model_validate(bad)
    assert "basis_citations" in str(exc.value)


# ---------------------------------------------------------------------------
# 5. test_registry_returns_correct_schema_per_mode
# ---------------------------------------------------------------------------


def test_registry_returns_correct_schema_per_mode() -> None:
    assert get_writer_schema("general") is GeneralReportPayload
    assert get_writer_schema("market_entry") is GeneralReportPayload
    assert get_writer_schema("due_diligence") is GeneralReportPayload
    assert get_writer_schema("growth_strategy") is GeneralReportPayload
    assert get_writer_schema("m_and_a_diligence") is MAndADiligenceReportPayload


# ---------------------------------------------------------------------------
# 6. test_registry_unknown_mode_returns_general
# ---------------------------------------------------------------------------


def test_registry_unknown_mode_returns_general() -> None:
    # Firm-defined modes (or typos) fall back to GeneralReportPayload —
    # the safe default.
    assert get_writer_schema("boutique_pricing_review") is GeneralReportPayload
    assert get_writer_schema("does_not_exist_xyz") is GeneralReportPayload
    assert get_writer_schema("") is GeneralReportPayload


# ---------------------------------------------------------------------------
# 7. test_legacy_alias_still_imports
# ---------------------------------------------------------------------------


def test_legacy_alias_still_imports() -> None:
    """W7/D1 hard rule: pre-W7 imports must keep working unchanged."""
    from models.report import WriterReportPayload

    # The alias is the same class object as GeneralReportPayload —
    # no copy, no reissue, so isinstance checks across the codebase
    # continue to pass.
    assert WriterReportPayload is GeneralReportPayload
    # And it still validates the legacy JSON shape.
    payload = WriterReportPayload.model_validate(_general_payload_json())
    assert isinstance(payload, WriterReportBase)
