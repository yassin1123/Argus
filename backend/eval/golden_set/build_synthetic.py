"""Synthetic golden-set backbone — Phase 5 / Week 21 / Day 1.

Hand-constructed claim–evidence pairs. The label is known **by
construction** — we wrote each piece of evidence to either:

  - directly establish the claim    → supported
  - support part of the claim       → partial
  - be topically related but silent → insufficient
  - state the opposite              → contradicted

No LLM was used to generate these labels (or the text). The
synthetic backbone is the reproducible foundation of the Week 21
accuracy bench.

Spread:
  - 60 pairs across 5 categories × 4 verdicts (3/cell)
  - ``adversarial=True`` flag on the deliberately subtle cases
    (magnitude mismatch, direction-only support, plausible
    irrelevance, mis-attribution) — those are the calibration-
    sensitive rows the Day 4 regression watches for.

The function :func:`build_synthetic_entries` is **deterministic**
— same input → identical output every run. The test asserts that;
a stable regression baseline is non-negotiable.
"""

from __future__ import annotations

from .types import Category, GoldenEntry, Verdict


# ---------------------------------------------------------------------------
# Synthetic pair factory
# ---------------------------------------------------------------------------


def _entry(
    idx: int, *,
    claim: str, evidence: str,
    verdict: Verdict, category: Category,
    rationale: str, adversarial: bool = False,
) -> GoldenEntry:
    return GoldenEntry(
        id=f"gs_{idx:03d}",
        claim=claim,
        evidence=evidence,
        evidence_source="synthetic",
        ground_truth=verdict.value,
        label_rationale=rationale,
        category=category.value,
        adversarial=adversarial,
    )


# Hand-built pair specs. Order is load-bearing — :func:`build_synthetic_entries`
# walks this list and ids are gs_001, gs_002, … in sequence so tests
# stay deterministic across edits.
_SPECS: list[dict] = [
    # ======================================================================
    # NUMERIC CLAIMS (12 entries — 3 per verdict)
    # ======================================================================
    # ---- supported ----
    dict(
        category=Category.NUMERIC, verdict=Verdict.SUPPORTED,
        claim="TargetCo's revenue grew 12% in FY2023.",
        evidence=(
            "Per the FY2023 annual report, TargetCo reported revenue of "
            "£50.4m, up 12% year-over-year from £45.0m in FY2022."
        ),
        rationale="Evidence states the exact 12% figure that's claimed.",
    ),
    dict(
        category=Category.NUMERIC, verdict=Verdict.SUPPORTED,
        claim="EBITDA margin expanded to 18% in FY2023.",
        evidence=(
            "FY2023 reported EBITDA was £9.1m on revenue of £50.4m, yielding "
            "an 18.06% EBITDA margin, up from 15.2% in FY2022."
        ),
        rationale="Evidence states the 18% margin directly.",
    ),
    dict(
        category=Category.NUMERIC, verdict=Verdict.SUPPORTED,
        claim="Operating cash flow exceeded £40m in FY2023.",
        evidence=(
            "Cash generated from operations in FY2023 was £42.3m, the highest "
            "since the FY2019 reorganisation."
        ),
        rationale="£42.3m exceeds the £40m threshold the claim asserts.",
    ),
    # ---- partial (magnitude mismatch — adversarial) ----
    dict(
        category=Category.NUMERIC, verdict=Verdict.PARTIAL,
        claim="Revenue grew by 20% in FY2023.",
        evidence=(
            "Revenue increased from £45m to £50.4m in FY2023, a 12% rise "
            "year-over-year."
        ),
        rationale=(
            "Evidence confirms revenue growth but at 12%, not 20% — direction "
            "supported, magnitude overstated."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.NUMERIC, verdict=Verdict.PARTIAL,
        claim="Free cash flow doubled to over £80m in FY2023.",
        evidence=(
            "Free cash flow in FY2023 was £42.3m, up from £30.1m in FY2022 — "
            "a 40% increase."
        ),
        rationale=(
            "Evidence confirms a meaningful FCF increase but the magnitude "
            "(40%, not 100%) and absolute (£42.3m, not £80m) are both wrong."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.NUMERIC, verdict=Verdict.PARTIAL,
        claim="Headcount grew 50% in FY2023.",
        evidence=(
            "Headcount as at year-end FY2023 stood at 1,140, compared with "
            "950 in FY2022."
        ),
        rationale=(
            "Implied growth is ~20% (1140/950), well below the claimed 50% — "
            "magnitude overstated."
        ),
        adversarial=True,
    ),
    # ---- insufficient (topical but silent on the figure) ----
    dict(
        category=Category.NUMERIC, verdict=Verdict.INSUFFICIENT,
        claim="TargetCo's revenue grew 12% in FY2023.",
        evidence=(
            "TargetCo's FY2023 results presentation emphasised the company's "
            "expanded distribution footprint and new product launches."
        ),
        rationale=(
            "Topically related (FY2023 results) but the evidence never states "
            "the revenue growth rate."
        ),
    ),
    dict(
        category=Category.NUMERIC, verdict=Verdict.INSUFFICIENT,
        claim="Capex was £15m in FY2023.",
        evidence=(
            "The CFO commentary noted that capex priorities in FY2023 "
            "centred on the new distribution centre and ERP rollout."
        ),
        rationale="Topic is right; the £15m figure is not stated.",
    ),
    dict(
        category=Category.NUMERIC, verdict=Verdict.INSUFFICIENT,
        claim="Net debt declined to £8m at FY2023 year-end.",
        evidence=(
            "Management commented that the deleveraging programme remained "
            "on track through FY2023, with continued debt repayment quarter "
            "on quarter."
        ),
        rationale=(
            "Direction implied but no figure given — the £8m claim is not "
            "established by this evidence."
        ),
        adversarial=True,
    ),
    # ---- contradicted ----
    dict(
        category=Category.NUMERIC, verdict=Verdict.CONTRADICTED,
        claim="Revenue grew 12% in FY2023.",
        evidence=(
            "Revenue declined 8% in FY2023, from £50m to £46m, driven by "
            "the loss of a key customer contract."
        ),
        rationale="Evidence states revenue declined; claim asserts growth.",
    ),
    dict(
        category=Category.NUMERIC, verdict=Verdict.CONTRADICTED,
        claim="EBITDA margin expanded in FY2023.",
        evidence=(
            "EBITDA margin compressed by 220 basis points to 12.8% in "
            "FY2023, the lowest level in five years."
        ),
        rationale="Margin compressed, not expanded.",
    ),
    dict(
        category=Category.NUMERIC, verdict=Verdict.CONTRADICTED,
        claim="Operating cash flow exceeded £40m in FY2023.",
        evidence=(
            "Operating cash flow in FY2023 was £18m, sharply lower than "
            "the £40m guidance issued at the start of the year."
        ),
        rationale="£18m is well below the £40m threshold the claim asserts.",
    ),

    # ======================================================================
    # CAUSAL CLAIMS (12 entries)
    # ======================================================================
    # ---- supported ----
    dict(
        category=Category.CAUSAL, verdict=Verdict.SUPPORTED,
        claim="The price increase in Q2 drove the margin expansion.",
        evidence=(
            "Management attributed the 220 bps gross-margin improvement in "
            "Q2 to the April price rise on the flagship product line, "
            "which more than offset the input-cost inflation seen in H1."
        ),
        rationale=(
            "Evidence explicitly attributes the margin improvement to the "
            "Q2 price increase."
        ),
    ),
    dict(
        category=Category.CAUSAL, verdict=Verdict.SUPPORTED,
        claim="The loss of the Acme contract caused the revenue decline.",
        evidence=(
            "The £6m revenue shortfall in H2 was driven by the non-renewal "
            "of the Acme master services agreement in October, which had "
            "contributed £8m of run-rate revenue."
        ),
        rationale="Direct causal attribution stated in the evidence.",
    ),
    dict(
        category=Category.CAUSAL, verdict=Verdict.SUPPORTED,
        claim="Supply chain delays drove the Q3 working-capital build.",
        evidence=(
            "Inventory increased £4m sequentially in Q3 as the company "
            "deliberately ordered ahead of expected port congestion at "
            "Felixstowe, a precaution that proved necessary as lead times "
            "extended through October."
        ),
        rationale="Evidence ties the WC build directly to the supply-chain action.",
    ),
    # ---- partial (one of several causes — adversarial) ----
    dict(
        category=Category.CAUSAL, verdict=Verdict.PARTIAL,
        claim="The pricing action alone drove the FY2023 margin expansion.",
        evidence=(
            "Margin expansion in FY2023 reflected the combined impact of "
            "the H1 price rise, the cost-out programme completed in Q2, "
            "and lower freight rates from May onwards."
        ),
        rationale=(
            "Pricing was one of three drivers; the 'alone' qualifier makes "
            "the claim only partially supported."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.CAUSAL, verdict=Verdict.PARTIAL,
        claim="Customer churn explains the revenue miss.",
        evidence=(
            "The revenue shortfall in FY2023 stemmed from a combination of "
            "lower new-logo wins (-£3m vs plan), modest customer churn "
            "(-£1m), and a delayed product launch (-£2m)."
        ),
        rationale=(
            "Churn contributed roughly 17% (£1m of £6m) of the miss — "
            "supported but partial."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.CAUSAL, verdict=Verdict.PARTIAL,
        claim="The reorganisation drove the productivity improvement.",
        evidence=(
            "Productivity improvements in FY2023 followed both the Q1 "
            "reorganisation and the rollout of the new field-service "
            "scheduling system in March; management estimates the two "
            "contributions as roughly equal."
        ),
        rationale="Half the improvement, not all of it.",
    ),
    # ---- insufficient ----
    dict(
        category=Category.CAUSAL, verdict=Verdict.INSUFFICIENT,
        claim="The price increase in Q2 drove the margin expansion.",
        evidence=(
            "Gross margin in Q2 FY2023 was 38.4%, up from 36.2% in Q1 "
            "FY2023. The company implemented a price increase across the "
            "core SKU portfolio effective 1 April."
        ),
        rationale=(
            "Evidence states both events but does not establish the causal "
            "link — the price increase could have been offset by other "
            "factors. Correlation, not causation."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.CAUSAL, verdict=Verdict.INSUFFICIENT,
        claim="The new CRM caused the sales-cycle compression.",
        evidence=(
            "The new CRM went live in June. Average sales-cycle length "
            "fell from 112 days in H1 to 89 days in H2."
        ),
        rationale=(
            "Temporal correlation only; the evidence offers no causal "
            "attribution and several other H2-only factors could explain it."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.CAUSAL, verdict=Verdict.INSUFFICIENT,
        claim="ESG investment drove the win-rate improvement.",
        evidence=(
            "The company increased ESG-related investment by £3m in FY2023 "
            "and saw win-rates improve from 22% to 28% over the same period."
        ),
        rationale=(
            "Two facts co-occur; the evidence does not attribute the "
            "improvement to the ESG investment."
        ),
    ),
    # ---- contradicted ----
    dict(
        category=Category.CAUSAL, verdict=Verdict.CONTRADICTED,
        claim="The reorganisation caused the productivity decline.",
        evidence=(
            "Following the Q1 reorganisation, output per FTE improved 14% "
            "sequentially in Q2 and a further 6% in Q3 — the strongest "
            "two-quarter run in the company's history."
        ),
        rationale="Evidence shows productivity improved, not declined.",
    ),
    dict(
        category=Category.CAUSAL, verdict=Verdict.CONTRADICTED,
        claim="The price cut drove the margin expansion.",
        evidence=(
            "The Q3 price cut directly compressed gross margin by 180 bps "
            "in the quarter, partly offsetting the cost-out savings the "
            "company had achieved earlier in the year."
        ),
        rationale="Price cut compressed margin, not expanded it.",
    ),
    dict(
        category=Category.CAUSAL, verdict=Verdict.CONTRADICTED,
        claim="Customer churn caused the FY2023 revenue growth.",
        evidence=(
            "Customer churn improved from 14% in FY2022 to 11% in FY2023; "
            "stronger retention was a meaningful contributor to FY2023 "
            "revenue growth."
        ),
        rationale=(
            "Evidence ties revenue growth to *lower* churn, not churn "
            "itself; the claim's direction is reversed."
        ),
        adversarial=True,
    ),

    # ======================================================================
    # COMPARATIVE (12 entries)
    # ======================================================================
    # ---- supported ----
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.SUPPORTED,
        claim="TargetCo outperformed its UK peer set on revenue growth in FY2023.",
        evidence=(
            "FY2023 revenue growth at TargetCo was 12%, versus a UK peer-"
            "set median of 4% (the peer set comprised the seven publicly "
            "listed comparables in the same sub-sector)."
        ),
        rationale="Evidence states both figures and the comparison.",
    ),
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.SUPPORTED,
        claim="TargetCo's gross margin is above the industry median.",
        evidence=(
            "TargetCo's FY2023 gross margin of 38.4% compares favourably "
            "with the industry median of 32.1% reported in the trade "
            "association's annual benchmark."
        ),
        rationale="Above-median position directly stated.",
    ),
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.SUPPORTED,
        claim="TargetCo's customer concentration is lower than CompetitorA's.",
        evidence=(
            "Top-10 customer concentration was 28% at TargetCo (FY2023) "
            "vs 47% at CompetitorA per CompetitorA's 2023 10-K filing."
        ),
        rationale="Two figures stated; the comparison follows.",
    ),
    # ---- partial ----
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.PARTIAL,
        claim="TargetCo outperformed its global peer set on both revenue growth and margin in FY2023.",
        evidence=(
            "FY2023 revenue growth at TargetCo (12%) exceeded the global "
            "peer-set median (5%). Margin performance was broadly in line "
            "with the peer median."
        ),
        rationale=(
            "Revenue-growth claim supported; margin outperformance not "
            "supported (in line, not above)."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.PARTIAL,
        claim="TargetCo leads the sector on customer satisfaction and price.",
        evidence=(
            "Customer-satisfaction scores ranked TargetCo #1 of 12 in the "
            "trade survey. Average selling price was the third-lowest in "
            "the same survey."
        ),
        rationale=(
            "Top on satisfaction (supported); third on price is not 'leads' "
            "(only supported in spirit, not literally)."
        ),
    ),
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.PARTIAL,
        claim="TargetCo outperformed its peers across every operating metric.",
        evidence=(
            "Across the five tracked operating metrics, TargetCo led on "
            "three (revenue growth, gross margin, sales-cycle length) and "
            "lagged on two (working-capital intensity, capex-to-revenue)."
        ),
        rationale="3 of 5, not 5 of 5.",
        adversarial=True,
    ),
    # ---- insufficient ----
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.INSUFFICIENT,
        claim="TargetCo outperformed its peer set on revenue growth.",
        evidence=(
            "TargetCo grew revenue 12% in FY2023, ahead of its own internal "
            "FY2023 plan of 8%."
        ),
        rationale=(
            "Evidence shows TargetCo beat its own plan; no peer comparison "
            "is established."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.INSUFFICIENT,
        claim="TargetCo's gross margin is above the industry median.",
        evidence=(
            "TargetCo's FY2023 gross margin was 38.4%, up from 36.2% in "
            "FY2022 and 33.8% in FY2021 — the company's third consecutive "
            "year of margin expansion."
        ),
        rationale=(
            "Margin trajectory shown; no industry-median benchmark cited."
        ),
    ),
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.INSUFFICIENT,
        claim="TargetCo leads its peer set on retention.",
        evidence=(
            "TargetCo's customer-retention rate of 89% in FY2023 was the "
            "highest in the company's history."
        ),
        rationale="Self-comparison, not peer comparison.",
    ),
    # ---- contradicted ----
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.CONTRADICTED,
        claim="TargetCo's revenue growth exceeded the peer median in FY2023.",
        evidence=(
            "FY2023 revenue growth at TargetCo (4%) was below the peer-set "
            "median (9%); the company underperformed its competitive set on "
            "the topline."
        ),
        rationale="Underperformed peers, not exceeded.",
    ),
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.CONTRADICTED,
        claim="TargetCo's customer concentration is lower than the industry average.",
        evidence=(
            "Top-10 customer concentration at TargetCo (47%) was meaningfully "
            "higher than the sector median of 28% in FY2023."
        ),
        rationale="Higher, not lower.",
    ),
    dict(
        category=Category.COMPARATIVE, verdict=Verdict.CONTRADICTED,
        claim="TargetCo's working capital intensity is best-in-class.",
        evidence=(
            "Working capital as a percentage of revenue at TargetCo (24%) "
            "was the highest in the comparable peer set; only one peer was "
            "more capital-intensive on a like-for-like basis."
        ),
        rationale="Highest, not lowest — worst-in-class.",
    ),

    # ======================================================================
    # ATTRIBUTION (12 entries)
    # ======================================================================
    # ---- supported ----
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.SUPPORTED,
        claim="The CEO said FY2024 EBITDA guidance is £12-14m.",
        evidence=(
            "Speaking on the Q4 FY2023 earnings call, CEO J. Walters "
            "guided FY2024 EBITDA to a range of £12-14m, with the midpoint "
            "subject to the timing of the new product launch."
        ),
        rationale="Direct attribution + range stated.",
    ),
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.SUPPORTED,
        claim="The auditor flagged the inventory valuation as a key audit matter.",
        evidence=(
            "PwC's FY2023 audit opinion identified inventory valuation as a "
            "key audit matter, citing the increased proportion of slow-"
            "moving stock following the Q3 product transition."
        ),
        rationale="Auditor + KAM + reason all stated.",
    ),
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.SUPPORTED,
        claim="The board approved the £20m share buyback in March 2024.",
        evidence=(
            "On 14 March 2024 the board approved a £20m share buyback "
            "programme, to be executed over the subsequent 12 months."
        ),
        rationale="Body + action + amount + timing all stated.",
    ),
    # ---- partial ----
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.PARTIAL,
        claim="The CEO and CFO both confirmed FY2024 guidance on the Q4 call.",
        evidence=(
            "On the Q4 FY2023 earnings call, CEO J. Walters reiterated "
            "FY2024 EBITDA guidance of £12-14m. The CFO took questions on "
            "working capital but did not address forward guidance directly."
        ),
        rationale="Only the CEO confirmed; CFO did not.",
        adversarial=True,
    ),
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.PARTIAL,
        claim="The auditor and the audit committee both raised concerns about inventory.",
        evidence=(
            "PwC's FY2023 opinion identified inventory valuation as a KAM. "
            "The audit committee chair's report in the annual report "
            "discussed cyber-security investment but did not refer to "
            "inventory."
        ),
        rationale="Auditor yes, audit committee no.",
        adversarial=True,
    ),
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.PARTIAL,
        claim="The board and management both endorsed the M&A strategy at the AGM.",
        evidence=(
            "Chairman opening remarks at the AGM included a clear "
            "endorsement of the inorganic-growth strategy. The CEO's "
            "AGM speech focused on operational priorities; the strategy "
            "was not addressed."
        ),
        rationale="Board endorsed, management didn't (per AGM).",
    ),
    # ---- insufficient ----
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.INSUFFICIENT,
        claim="The CEO said FY2024 EBITDA guidance is £12-14m.",
        evidence=(
            "On the Q4 FY2023 earnings call, management reiterated their "
            "constructive outlook on the FY2024 operating environment and "
            "the expected benefits from the cost-out programme."
        ),
        rationale=(
            "Right call, right topic — but no specific EBITDA guidance "
            "figure or speaker attribution given."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.INSUFFICIENT,
        claim="The CFO confirmed the dividend would be maintained.",
        evidence=(
            "Dividend policy was discussed on the Q4 earnings call by "
            "management. The Q3 release had previously affirmed the "
            "company's commitment to a progressive dividend."
        ),
        rationale=(
            "Topic discussed but no specific CFO attribution or 'maintained' "
            "commitment stated."
        ),
    ),
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.INSUFFICIENT,
        claim="The board approved the £20m share buyback in March 2024.",
        evidence=(
            "The Chairman's annual statement, dated April 2024, referred "
            "to capital-return mechanisms being kept under active review "
            "given the strong FY2023 cash generation."
        ),
        rationale=(
            "Capital return discussed but no buyback approval, no £20m, "
            "no March date."
        ),
    ),
    # ---- contradicted ----
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.CONTRADICTED,
        claim="The CEO guided FY2024 EBITDA above £14m.",
        evidence=(
            "On the Q4 call, the CEO guided FY2024 EBITDA to £10-12m, "
            "down from the prior consensus range of £12-14m."
        ),
        rationale="Guidance was below £14m, not above.",
    ),
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.CONTRADICTED,
        claim="The auditor issued an unqualified opinion in FY2023.",
        evidence=(
            "PwC issued a qualified opinion on the FY2023 financial "
            "statements, with the qualification relating to the "
            "recoverability of receivables from a specific customer "
            "that entered administration in Q4."
        ),
        rationale="Qualified, not unqualified.",
    ),
    dict(
        category=Category.ATTRIBUTION, verdict=Verdict.CONTRADICTED,
        claim="The board rejected the proposed share buyback.",
        evidence=(
            "The board approved the proposed £20m share buyback programme "
            "at its March 2024 meeting; execution commenced in April."
        ),
        rationale="Approved, not rejected.",
    ),

    # ======================================================================
    # FORECAST (12 entries)
    # ======================================================================
    # ---- supported ----
    dict(
        category=Category.FORECAST, verdict=Verdict.SUPPORTED,
        claim="Management expects FY2024 EBITDA growth of 15%.",
        evidence=(
            "FY2024 guidance, issued with the Q4 FY2023 results, projects "
            "EBITDA of £12-14m vs FY2023 actual of £10.4m — a midpoint "
            "growth rate of 15.4%."
        ),
        rationale="The 15% growth claim follows directly from the midpoint of guidance.",
    ),
    dict(
        category=Category.FORECAST, verdict=Verdict.SUPPORTED,
        claim="The company expects to be net-debt-free by FY2025.",
        evidence=(
            "Treasury commentary at the FY2023 results stated the company "
            "expects to reach a net-cash position during FY2025 on the "
            "current deleveraging trajectory."
        ),
        rationale="Expectation directly stated.",
    ),
    dict(
        category=Category.FORECAST, verdict=Verdict.SUPPORTED,
        claim="Capex is expected to rise to £20m in FY2024.",
        evidence=(
            "FY2024 capex is guided to £20m, up from £15m in FY2023, "
            "principally reflecting the new manufacturing-line investment."
        ),
        rationale="Guidance figure matches the claim exactly.",
    ),
    # ---- partial ----
    dict(
        category=Category.FORECAST, verdict=Verdict.PARTIAL,
        claim="Management expects FY2024 EBITDA and revenue growth above 15%.",
        evidence=(
            "FY2024 EBITDA is guided to grow ~15% to £12m. Revenue growth "
            "guidance is 7-9%, materially below the EBITDA growth rate."
        ),
        rationale=(
            "EBITDA claim broadly supported; revenue 'above 15%' is not."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.FORECAST, verdict=Verdict.PARTIAL,
        claim="The company expects to be both net-debt-free and dividend-paying by FY2025.",
        evidence=(
            "Net cash position is expected during FY2025. Dividend "
            "reinstatement is described as 'subject to ongoing capital "
            "allocation review' and is not part of the FY2024-25 plan."
        ),
        rationale="Net-cash supported; dividend by FY2025 not.",
    ),
    dict(
        category=Category.FORECAST, verdict=Verdict.PARTIAL,
        claim="FY2024 capex will rise materially and free cash flow will improve.",
        evidence=(
            "Capex is guided to £20m in FY2024 (+33%). Free cash flow "
            "guidance was not disclosed; the CFO referenced 'capex-led "
            "pressure on FCF in the near term'."
        ),
        rationale=(
            "Capex rise supported. FCF improvement not — in fact the CFO "
            "indicated near-term pressure."
        ),
        adversarial=True,
    ),
    # ---- insufficient ----
    dict(
        category=Category.FORECAST, verdict=Verdict.INSUFFICIENT,
        claim="Management expects FY2024 EBITDA growth of 15%.",
        evidence=(
            "Management commentary at the FY2023 results highlighted a "
            "broadly positive outlook for FY2024, with cost discipline "
            "and pricing maintained as key levers."
        ),
        rationale=(
            "Positive directional outlook only — no quantitative growth "
            "rate stated."
        ),
        adversarial=True,
    ),
    dict(
        category=Category.FORECAST, verdict=Verdict.INSUFFICIENT,
        claim="The company expects FY2024 revenue of £56m.",
        evidence=(
            "FY2024 guidance was issued with the FY2023 results and "
            "centred on margin and capital-return metrics. Revenue "
            "guidance was not disclosed."
        ),
        rationale="Revenue guidance not stated.",
    ),
    dict(
        category=Category.FORECAST, verdict=Verdict.INSUFFICIENT,
        claim="The company expects capex to fall in FY2024.",
        evidence=(
            "Capital allocation priorities for FY2024 were discussed at "
            "the FY2023 results presentation, with a focus on the new "
            "manufacturing line and digital infrastructure."
        ),
        rationale="Direction of capex (up/down) not stated.",
    ),
    # ---- contradicted ----
    dict(
        category=Category.FORECAST, verdict=Verdict.CONTRADICTED,
        claim="Management expects FY2024 EBITDA growth of 15%.",
        evidence=(
            "FY2024 EBITDA is guided to £8-9m vs FY2023 actual of £10.4m — "
            "implying a 15-23% decline, materially below the consensus "
            "growth expectation."
        ),
        rationale="Guidance implies a decline, not growth.",
    ),
    dict(
        category=Category.FORECAST, verdict=Verdict.CONTRADICTED,
        claim="The company expects net debt to fall in FY2024.",
        evidence=(
            "Net debt is expected to rise to £45m at FY2024 year-end "
            "(from £38m at FY2023 year-end) reflecting the planned "
            "step-up in capex and the bolt-on acquisition completed in "
            "Q1 FY2024."
        ),
        rationale="Net debt expected to rise, not fall.",
    ),
    dict(
        category=Category.FORECAST, verdict=Verdict.CONTRADICTED,
        claim="Capex is expected to fall in FY2024.",
        evidence=(
            "FY2024 capex is guided to £20m, up from £15m in FY2023 — a "
            "33% increase principally reflecting the new manufacturing-"
            "line investment."
        ),
        rationale="Capex up 33%, not falling.",
    ),
]


def build_synthetic_entries() -> list[GoldenEntry]:
    """Return the synthetic backbone — deterministic, repeatable.
    Same call → identical list every time."""
    return [
        _entry(
            i + 1,
            claim=spec["claim"],
            evidence=spec["evidence"],
            verdict=spec["verdict"],
            category=spec["category"],
            rationale=spec["rationale"],
            adversarial=spec.get("adversarial", False),
        )
        for i, spec in enumerate(_SPECS)
    ]


__all__ = ["build_synthetic_entries"]
