"""Phase 2 / Week 7 / Iterate — shared M&A fixture helpers.

The single export, :func:`build_minimal_valid_m_and_a_payload`, returns a
fully-populated ``MAndADiligenceReportPayload`` instance whose every
field would survive the Day-1 schema validators AND the Day-3 critic
checks. Used by ``test_m_and_a_downstream.py`` to verify the post-
writer path (critic + renderer + structural assertions) works
independently of whether a real LLM run produces conforming output.

The numbers are loosely modeled on the synthetic TargetCo CIM
(``targetco_cim.md``) so the payload reads as a plausible M&A memo
rather than a Lorem-Ipsum stand-in. None of it is real.
"""

from __future__ import annotations

from agents.writer.schemas import (
    ComparableTransaction,
    DealStructureImplications,
    EBITDATrajectory,
    FinancialProfile,
    GeographyExposure,
    InitiativeBlock,
    IntegrationPlan,
    MAndADiligenceReportPayload,
    MarginProfile,
    NPVRange,
    RevenueTrajectory,
    RiskAssessment,
    Segment,
    SourceItem,
    Synergy,
    SynergyEstimate,
    TargetOverview,
    TrajectoryPoint,
    ValuationPoint,
    ValuationRange,
)


def build_minimal_valid_m_and_a_payload() -> MAndADiligenceReportPayload:
    """Build a fully-populated, valid M&A diligence payload.

    Every nested type carries the minimum content its validators
    require (Synergy.basis_citations non-empty, ValuationPoint
    methodology non-empty, valuation monotonic low<=base<=high,
    multiples_implied includes EV/EBITDA + EV/Sales, walk_away_triggers
    contain digits/percentages, etc.).
    """
    return MAndADiligenceReportPayload(
        recommendation=(
            "PROCEED WITH CONDITIONS — acquire TargetCo Holdings at "
            "£195-210m EV (7.6-8.2x FY24 Adj EBITDA) gated on Halo "
            "renewal probability ≥60% by Week 8 and ROI divestment "
            "bids ≥£9.5m by Week 10."
        ),
        confidence_level="Medium-High",
        summary=(
            "TargetCo is a £180m UK industrial-services platform with "
            "13.3% Adj EBITDA margin and 61.7% FCF conversion. The "
            "biggest reason to act is the diversified four-segment "
            "mix that delivers 91% recurring revenue on 4.7-year "
            "contracts. The biggest risk is the £18m/year Project "
            "Halo contract renewing in 14 months; gated by a Week 8 "
            "renewal-probability read."
        ),
        key_reasons=[
            "Concentrates 60% of revenue in Facilities Maintenance + Compliance — both 14%+ EBITDA margins.",
            "Working capital cycle improved 13 days (64→51) over FY21-FY24; £6m cash unlock potential.",
            "Compliance segment growing 11% YoY at 22% margin — sector best-in-class.",
            "Sponsor exit window (24 months) aligns with our hold horizon.",
        ],
        risks=[
            "Project Halo £18m renewal in 14 months — 10% revenue / 14% EBITDA exposure.",
            "Sept 2026 debt maturity inside the deal hold period.",
            "Mechanical Services pipeline conversion is below FY-trend.",
        ],
        counterarguments=[
            "Sector multiples expanding suggests we should pay up — rebutted by the £8m DB pension drag.",
        ],
        next_steps=[
            "This week: Sign LOI at £210m headline.",
            "Within 30 days: Independent benchmark of Halo renewal probability.",
            "Within 90 days: Validate Mechanical pipeline conversion in week-12 read.",
            "By month 6: Lock supplier-side renegotiation deltas.",
            "Month 9: review Home LFL; if <-1.5%, slow Home capex.",
        ],
        sources=[
            SourceItem(title="TargetCo Holdings — Project Lighthouse CIM", type="document"),
            SourceItem(title="UK Industrial Services Sector Primer", type="knowledge"),
        ],
        caveats="DB pension actuarial assumptions un-diligenced; succession risk un-quantified.",
        kill_criteria=[
            "If Halo renewal probability <40% at Week 8, walk.",
            "If ROI divestment lands <£8m, renegotiate at -£15m headline.",
        ],
        what_would_change_our_mind=(
            "Hard evidence Halo renewal is locked at <8% pricing concession would lift "
            "the recommendation to PROCEED unconditional."
        ),
        evidence_ledger_summary=(
            "CIM (audited financials), management Q&A (8 questions), 3 comparable "
            "transactions cited at 7.2-9.5x EV/EBITDA."
        ),
        target_overview=TargetOverview(
            name="TargetCo Holdings Ltd",
            business_model=(
                "UK industrial services group; four-segment portfolio "
                "(Facilities Maintenance 52%, Industrial Cleaning 24%, "
                "Mechanical Services 16%, Compliance Auditing 8%); 950 FTE; "
                "Bristol HQ; founded 1987."
            ),
            segments=[
                Segment(name="Facilities Maintenance", revenue_pct=52.0, growth_rate="+8.0%"),
                Segment(name="Industrial Cleaning", revenue_pct=24.0, growth_rate="+2.0%"),
                Segment(name="Mechanical Services", revenue_pct=16.0, growth_rate="+6.0%"),
                Segment(name="Compliance Auditing", revenue_pct=8.0, growth_rate="+11.0%"),
            ],
            geographies=[
                GeographyExposure(geography="UK", revenue_pct=91.0),
                GeographyExposure(geography="Republic of Ireland", revenue_pct=9.0),
            ],
            ownership_history=(
                "Marylebone Partners III LP holds 71% (acquired March 2020); "
                "founder family 22%; management EMI pool 7%."
            ),
            key_customers_concentration=(
                "Top-5 customers = 31% of revenue; top-10 = 44%. Largest single "
                "exposure is the £18m/year Project Halo contract."
            ),
        ),
        financial_profile=FinancialProfile(
            revenue_trajectory=RevenueTrajectory(
                points=[
                    TrajectoryPoint(period="FY22", value_gbp_m=162.4, growth_rate="+6.0%", source_citation="CIM §5"),
                    TrajectoryPoint(period="FY23", value_gbp_m=173.1, growth_rate="+6.6%", source_citation="CIM §5"),
                    TrajectoryPoint(period="FY24", value_gbp_m=180.0, growth_rate="+4.0%", source_citation="CIM §5"),
                    TrajectoryPoint(period="LTM Q1", value_gbp_m=182.1, growth_rate="+3.5%", source_citation="CIM §5"),
                ],
                notes="Audited through FY24; LTM from management accounts.",
            ),
            ebitda_trajectory=EBITDATrajectory(
                points=[
                    TrajectoryPoint(period="FY22", value_gbp_m=20.6, growth_rate=None, source_citation="CIM §5"),
                    TrajectoryPoint(period="FY24", value_gbp_m=24.0, growth_rate="+5.8%", source_citation="CIM §5"),
                ],
                notes="Adj EBITDA £25.6m FY24; £1.6m of management adjustments.",
            ),
            margin_profile=MarginProfile(
                gross_margin="36.4%",
                ebitda_margin="13.3%",
                fcf_margin="8.2%",
                trend_commentary="130bps margin expansion FY21-FY24 driven by Compliance mix gain.",
            ),
            working_capital_dynamics="DSO 64→51 days FY21-FY24; centralised credit control + e-invoicing.",
            debt_structure="£35m senior term loan (Lloyds, SONIA+275); September 2026 bullet.",
            capex_intensity="2.3% of revenue; 60% maintenance, 40% growth.",
            cash_flow_quality="61.7% conversion of EBITDA; recurring contracts dominate.",
        ),
        synergy_estimate=SynergyEstimate(
            revenue_synergies=[
                Synergy(
                    type="Cross-sell Compliance to Facilities customer base",
                    magnitude_gbp_m=4.2,
                    timing_months=18,
                    confidence="medium",
                    basis_citations=["CIM §2.4 — 22.2% Compliance margin, 95% retainer revenue"],
                ),
            ],
            cost_synergies=[
                Synergy(
                    type="Procurement consolidation across portfolio",
                    magnitude_gbp_m=1.8,
                    timing_months=12,
                    confidence="high",
                    basis_citations=["CIM §6 — overlapping supplier base"],
                ),
            ],
            dis_synergies=[
                Synergy(
                    type="Customer attrition during integration",
                    magnitude_gbp_m=1.4,
                    timing_months=9,
                    confidence="medium",
                    basis_citations=["CIM §3 — top-5 customer concentration"],
                ),
            ],
            net_present_value=NPVRange(
                low_gbp_m=12.0, base_gbp_m=22.0, high_gbp_m=38.0, discount_rate_pct=11.5
            ),
            realization_timeline="Year 1 30% / Year 2 75% / Year 3 100% of run-rate.",
        ),
        risks_and_mitigations=[
            RiskAssessment(
                risk_category="commercial",
                description="Project Halo £18m contract renewal at the 14-month mark.",
                severity="high",
                mitigation="Independent benchmark by Week 8; backstop accounts pre-identified.",
                residual_risk="Loss of Halo cuts EBITDA by ~14% even with backstop ramp.",
            ),
        ],
        integration_plan=IntegrationPlan(
            day_one_priorities=[
                "Payroll continuity for 950 FTE",
                "Customer comms to top-50 accounts",
                "ERP read-only for buyer team",
            ],
            first_100_days=[
                InitiativeBlock(
                    workstream="Halo renewal preparation",
                    owner_role="Pricing Director",
                    milestone="Week-6 renewal-probability read at ≥60%",
                    dependencies=["Bank procurement-team interviews"],
                ),
                InitiativeBlock(
                    workstream="Procurement consolidation",
                    owner_role="CFO",
                    milestone="Week-10 supplier rationalisation plan signed off",
                    dependencies=["IT system overlap audit"],
                ),
                InitiativeBlock(
                    workstream="ROI divestment process",
                    owner_role="Head of M&A",
                    milestone="Week-12 indicative bids ≥£9.5m",
                    dependencies=["Independent valuation"],
                ),
            ],
            first_year=[
                InitiativeBlock(
                    workstream="Compliance cross-sell program",
                    owner_role="Group Operations Director",
                    milestone="£4.2m incremental cross-sell revenue by month 18",
                    dependencies=["Sales-team incentive redesign"],
                ),
            ],
            integration_complexity_rating="medium",
            complexity_rationale="Single-geography, single-ERP base; segment heterogeneity raises complexity.",
        ),
        valuation_range=ValuationRange(
            low=ValuationPoint(
                gbp_m=185.0,
                methodology="DCF @ WACC 12% with terminal growth 2.0%; conservative Halo loss case",
                key_assumptions=["Halo lost at renewal", "Supplier renegotiation £6m"],
            ),
            base=ValuationPoint(
                gbp_m=210.0,
                methodology="DCF @ WACC 11.5% triangulated against EV/EBITDA 8.5x precedents",
                key_assumptions=["Halo renews at -8% pricing", "Supplier renegotiation £12m"],
            ),
            high=ValuationPoint(
                gbp_m=235.0,
                methodology="EV/EBITDA 9.5x precedent transactions in UK industrial services FY22-24",
                key_assumptions=["Halo renews at flat pricing", "Compliance growth accelerates to 14% YoY"],
            ),
            multiples_implied={"EV/EBITDA": 8.2, "EV/Sales": 1.17},
            comparable_transactions_cited=[
                ComparableTransaction(
                    target="Crestwood Group",
                    acquirer="Sentinel Capital Partners",
                    year=2023,
                    multiple="9.5x EV/EBITDA",
                    source_citation="UK mid-cap Mergermarket DB",
                ),
                ComparableTransaction(
                    target="Brighton FM Ltd",
                    acquirer="Quantum Industrial",
                    year=2023,
                    multiple="8.1x EV/EBITDA",
                    source_citation="Press release + intermediary",
                ),
            ],
        ),
        deal_structure_implications=DealStructureImplications(
            recommended_structure=(
                "Share purchase, 70% cash + 30% rolled equity from sponsor with 3-year vest; "
                "£15m earn-out tied to year-2 EBITDA bridge."
            ),
            rationale=(
                "Rolled equity aligns sponsor through transition; earn-out shifts Halo "
                "renewal risk to the seller."
            ),
            negotiation_priorities=[
                "Management retention package locked at LOI",
                "Working-capital peg at 51 days",
                "Earn-out trigger above £24m EBITDA at year-2",
            ],
            walk_away_triggers=[
                "If Halo renewal probability < 40% at Week 8, walk.",
                "If top-3 customers > 45% of revenue at close, walk.",
                "If ERP migration estimate exceeds £4m, renegotiate.",
            ],
        ),
    )
