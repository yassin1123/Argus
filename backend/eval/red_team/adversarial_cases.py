"""Adversarial claim-evidence pairs — Phase 5 / Week 21 / Day 4.

Hand-built attacks across 8 exploit categories. Every pair's
ground truth is NOT ``supported``; the goal is to find the
specific classes the tuned ensemble cannot catch and either fix
them (Day 3-style retune) or document them as known limitations
(the targeted numeric-consistency probe is one mitigation).

Constructed deterministically — same call returns the same list,
so red-team accuracy is a stable regression baseline that Day 5
can diff against and Week 22+ can monitor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ExploitType(str, Enum):
    """The eight attack categories the W21/D4 spec calls out."""

    MAGNITUDE_MISMATCH = "magnitude_mismatch"
    MISATTRIBUTION = "misattribution"
    TEMPORAL_DRIFT = "temporal_drift"
    OVERCLAIM = "overclaim"
    FABRICATED_SPECIFIC = "fabricated_specific"
    PLAUSIBLE_BUT_ABSENT = "plausible_but_absent"
    NEGATION_FLIP = "negation_flip"
    CHERRY_PICK = "cherry_pick"


@dataclass
class AdversarialCase:
    """One red-team (claim, evidence) attack.

    ``expected_verdict`` is ALWAYS one of {partial, insufficient,
    contradicted} — never "supported". An escape is when the
    verifier returns supported on this pair.
    """

    id: str
    exploit_type: str
    claim: str
    evidence: str
    expected_verdict: str          # partial | insufficient | contradicted
    rationale: str                 # why a verifier might be tempted to call this supported

    def __post_init__(self) -> None:
        valid_truth = {"partial", "insufficient", "contradicted"}
        if self.expected_verdict not in valid_truth:
            raise ValueError(
                f"AdversarialCase {self.id}: ground truth must be in "
                f"{valid_truth}; got {self.expected_verdict!r}. "
                "Spec hard rule: every red-team case is NOT-supported."
            )
        valid_exploit = {t.value for t in ExploitType}
        if self.exploit_type not in valid_exploit:
            raise ValueError(
                f"AdversarialCase {self.id}: unknown exploit_type "
                f"{self.exploit_type!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _case(
    idx: int,
    exploit: ExploitType,
    claim: str,
    evidence: str,
    expected: str,
    rationale: str,
) -> AdversarialCase:
    return AdversarialCase(
        id=f"rt_{idx:03d}",
        exploit_type=exploit.value,
        claim=claim,
        evidence=evidence,
        expected_verdict=expected,
        rationale=rationale,
    )


_SPECS: list[dict] = [
    # ======================================================================
    # MAGNITUDE MISMATCH — direction right, number wrong (the most common
    # hallucination class in financial deliverables)
    # ======================================================================
    dict(exploit=ExploitType.MAGNITUDE_MISMATCH, expected="partial",
         claim="Revenue grew 25% in FY2023.",
         evidence="Revenue increased from £40m to £46m in FY2023 — a 15% rise.",
         rationale="Both say 'revenue grew' — the LLM may anchor on gist."),
    dict(exploit=ExploitType.MAGNITUDE_MISMATCH, expected="partial",
         claim="EBITDA margin expanded 400 basis points.",
         evidence="EBITDA margin expanded 120 basis points to 14.2%.",
         rationale="Direction supported, magnitude overstated by 3x."),
    dict(exploit=ExploitType.MAGNITUDE_MISMATCH, expected="partial",
         claim="Customer churn fell to 8% in FY2023.",
         evidence="Customer churn improved to 12% in FY2023, down from 14%.",
         rationale="Improvement direction right; absolute level wrong."),
    dict(exploit=ExploitType.MAGNITUDE_MISMATCH, expected="partial",
         claim="Free cash flow doubled YoY to £80m.",
         evidence="Free cash flow rose 35% to £42m in FY2023.",
         rationale="Both 'rose' but doubled (100%) vs 35%; £80m vs £42m."),

    # ======================================================================
    # MISATTRIBUTION — right facts, wrong source/speaker
    # ======================================================================
    dict(exploit=ExploitType.MISATTRIBUTION, expected="insufficient",
         claim="The CFO said FY2024 EBITDA will be £14m.",
         evidence=(
             "On the Q4 earnings call, CEO J. Walters guided FY2024 EBITDA to "
             "£12-14m. The CFO declined to comment on forward guidance."
         ),
         rationale="Right number, right call — wrong speaker."),
    dict(exploit=ExploitType.MISATTRIBUTION, expected="insufficient",
         claim="PwC identified the loan-loss provision as a key audit matter.",
         evidence=(
             "PwC's FY2023 opinion identified inventory valuation as a key "
             "audit matter. Loan-loss provisioning was reviewed by internal "
             "audit, not the external auditor."
         ),
         rationale="Right auditor, right topic class — wrong issue attributed."),
    dict(exploit=ExploitType.MISATTRIBUTION, expected="insufficient",
         claim="The board chair endorsed the cost-out programme at the AGM.",
         evidence=(
             "The CEO's AGM speech endorsed the cost-out programme. The chair's "
             "opening remarks focused on board renewal."
         ),
         rationale="Endorsement happened; wrong person attributed."),
    dict(exploit=ExploitType.MISATTRIBUTION, expected="insufficient",
         claim="Moody's downgraded TargetCo to Baa3 in October 2023.",
         evidence=(
             "S&P downgraded TargetCo to BBB- in October 2023, citing weaker "
             "interest coverage. Moody's rating was unchanged at Baa2."
         ),
         rationale="Right action, right month — wrong rating agency."),

    # ======================================================================
    # TEMPORAL DRIFT — right facts, wrong period
    # ======================================================================
    dict(exploit=ExploitType.TEMPORAL_DRIFT, expected="insufficient",
         claim="Revenue grew 12% in FY2023.",
         evidence=(
             "Revenue grew 12% in FY2022, from £40m to £44.8m. FY2023 results "
             "have not yet been disclosed."
         ),
         rationale="Right growth rate, right company — wrong fiscal year."),
    dict(exploit=ExploitType.TEMPORAL_DRIFT, expected="insufficient",
         claim="Q3 FY2024 net debt stood at £35m.",
         evidence=(
             "Q3 FY2023 net debt stood at £35m, down from £42m in the prior "
             "quarter. Q3 FY2024 results are due in November."
         ),
         rationale="Identical number, wrong period."),
    dict(exploit=ExploitType.TEMPORAL_DRIFT, expected="insufficient",
         claim="The Q4 FY2024 share buyback was completed in March 2024.",
         evidence=(
             "The Q4 FY2023 share buyback completed in March 2024 (after the "
             "fiscal year end). Q4 FY2024 buyback plans have not been announced."
         ),
         rationale="March 2024 date matches; the year-attribution is wrong."),
    dict(exploit=ExploitType.TEMPORAL_DRIFT, expected="contradicted",
         claim="The reorganisation was completed in FY2024.",
         evidence=(
             "The reorganisation was completed in Q1 FY2023, well ahead of the "
             "original FY2024 timeline."
         ),
         rationale="Ahead-of-plan completion: claim's year is contradicted."),

    # ======================================================================
    # OVERCLAIM — strong version of a weak statement
    # ======================================================================
    dict(exploit=ExploitType.OVERCLAIM, expected="partial",
         claim="TargetCo dominates the UK mid-market segment.",
         evidence=(
             "TargetCo holds a 14% share of the UK mid-market segment, the "
             "largest single share but well below 'dominant' positioning."
         ),
         rationale="Largest share != dominant; the LLM may treat them as synonymous."),
    dict(exploit=ExploitType.OVERCLAIM, expected="partial",
         claim="The product launch was a runaway success.",
         evidence=(
             "Q3 sales of the new product exceeded plan by 8%, contributing "
             "£1.4m of revenue."
         ),
         rationale="8% beat is not 'runaway success'."),
    dict(exploit=ExploitType.OVERCLAIM, expected="partial",
         claim="Operating leverage is fully realised at this scale.",
         evidence=(
             "FY2023 operating leverage of 1.3x indicates meaningful but not "
             "fully realised scale benefits."
         ),
         rationale="'Meaningful' is being inflated to 'fully realised'."),
    dict(exploit=ExploitType.OVERCLAIM, expected="partial",
         claim="Customer satisfaction is best-in-class across the sector.",
         evidence=(
             "TargetCo ranked 3rd of 12 on customer satisfaction in the trade "
             "survey, an improvement from 7th in the prior year."
         ),
         rationale="3rd is not best-in-class."),

    # ======================================================================
    # FABRICATED SPECIFIC — precise number/fact that isn't in the evidence
    # ======================================================================
    dict(exploit=ExploitType.FABRICATED_SPECIFIC, expected="insufficient",
         claim="TargetCo's gross margin improved by exactly 247 basis points.",
         evidence=(
             "Gross margin expanded materially in FY2023 driven by the "
             "pricing programme and lower input costs."
         ),
         rationale="247 bps is fabricated; evidence is qualitative only."),
    dict(exploit=ExploitType.FABRICATED_SPECIFIC, expected="insufficient",
         claim="The acquisition will deliver £3.7m of cost synergies by year three.",
         evidence=(
             "Management cited 'meaningful cost synergies' from the acquisition, "
             "with timing dependent on integration milestones."
         ),
         rationale="£3.7m + year three are both fabricated specifics."),
    dict(exploit=ExploitType.FABRICATED_SPECIFIC, expected="insufficient",
         claim="The CEO holds 8.4% of outstanding shares.",
         evidence=(
             "The CEO is a meaningful shareholder; the company's beneficial-"
             "ownership filings disclose senior-executive holdings annually."
         ),
         rationale="8.4% is fabricated; evidence is generic."),
    dict(exploit=ExploitType.FABRICATED_SPECIFIC, expected="insufficient",
         claim="Net working capital was 18.2 days at FY2023 year-end.",
         evidence=(
             "Working-capital efficiency improved through FY2023 reflecting the "
             "new collections process."
         ),
         rationale="18.2 days is a fabricated precise figure."),
    dict(exploit=ExploitType.FABRICATED_SPECIFIC, expected="insufficient",
         claim="Engineering headcount stood at 247 at FY2023 year-end.",
         evidence="Engineering team grew through FY2023 driven by the platform rebuild.",
         rationale="247 is fabricated; evidence states only the direction."),

    # ======================================================================
    # PLAUSIBLE BUT ABSENT — the kind of thing the evidence would say but doesn't
    # ======================================================================
    dict(exploit=ExploitType.PLAUSIBLE_BUT_ABSENT, expected="insufficient",
         claim="TargetCo has positive net cash of £12m.",
         evidence=(
             "Treasury commentary at the FY2023 results discussed capital "
             "allocation priorities including ongoing debt repayment, dividend "
             "policy, and selective bolt-on M&A."
         ),
         rationale="Capital position is the natural topic; evidence simply doesn't address it."),
    dict(exploit=ExploitType.PLAUSIBLE_BUT_ABSENT, expected="insufficient",
         claim="The company's effective tax rate is 19%.",
         evidence=(
             "Tax expense for FY2023 reflected the standard UK corporate rate "
             "with adjustments for R&D tax credits and prior-year items."
         ),
         rationale="Tax discussed; no rate stated."),
    dict(exploit=ExploitType.PLAUSIBLE_BUT_ABSENT, expected="insufficient",
         claim="Cash conversion was 85% in FY2023.",
         evidence=(
             "Cash conversion remained strong in FY2023 supported by working-"
             "capital discipline and a benign capex year."
         ),
         rationale="'Strong' is not 85% — the figure is absent."),

    # ======================================================================
    # NEGATION FLIP — claim asserts what evidence denies, subtly
    # ======================================================================
    dict(exploit=ExploitType.NEGATION_FLIP, expected="contradicted",
         claim="The company plans to expand into Germany in FY2024.",
         evidence=(
             "The company has no plans to enter Germany in FY2024, with European "
             "expansion focused on the Nordics."
         ),
         rationale="Negation easy to miss in a long sentence."),
    dict(exploit=ExploitType.NEGATION_FLIP, expected="contradicted",
         claim="The board approved the dividend increase.",
         evidence=(
             "The board considered but did not approve the proposed dividend "
             "increase at its March meeting, citing capital-allocation flexibility."
         ),
         rationale="'Did not approve' embedded in approval-context sentence."),
    dict(exploit=ExploitType.NEGATION_FLIP, expected="contradicted",
         claim="The new ERP rollout is on schedule.",
         evidence=(
             "The new ERP rollout has slipped by two quarters; the revised "
             "go-live is now Q2 FY2025."
         ),
         rationale="Slip vs on-schedule."),
    dict(exploit=ExploitType.NEGATION_FLIP, expected="contradicted",
         claim="Audit findings were free of material weaknesses.",
         evidence=(
             "The FY2023 audit identified a material weakness in revenue-"
             "recognition controls, since remediated."
         ),
         rationale="Material weakness present; 'since remediated' may distract the judge."),

    # ======================================================================
    # CHERRY-PICK — true of one data point, evidence shows it's not general
    # ======================================================================
    dict(exploit=ExploitType.CHERRY_PICK, expected="partial",
         claim="Quarterly revenue growth accelerated through FY2023.",
         evidence=(
             "Quarterly YoY revenue growth was Q1: 18%, Q2: 14%, Q3: 11%, "
             "Q4: 16%."
         ),
         rationale="Q4 accelerated vs Q3; over the year, the trend was deceleration with a Q4 bump."),
    dict(exploit=ExploitType.CHERRY_PICK, expected="partial",
         claim="Customer satisfaction improved across every product line.",
         evidence=(
             "NPS improved in four of the six product lines in FY2023; the "
             "two lagging lines saw modest declines that are being addressed."
         ),
         rationale="Four of six is not 'every'."),
    dict(exploit=ExploitType.CHERRY_PICK, expected="partial",
         claim="Gross margin expanded across all regions in FY2023.",
         evidence=(
             "FY2023 gross margin expanded in the UK and DACH; APAC and the "
             "Americas saw modest contraction."
         ),
         rationale="Two regions up, two down — the claim asserts uniformity that isn't there."),
    dict(exploit=ExploitType.CHERRY_PICK, expected="partial",
         claim="Every senior leader had a positive scorecard in FY2023.",
         evidence=(
             "5 of 8 senior leaders received scorecards above plan in FY2023; "
             "the other 3 had mixed outcomes attributed to one-off factors."
         ),
         rationale="5 of 8 != every."),

    # ======================================================================
    # FABRICATED + MISATTRIBUTION combo (the worst kind: a made-up number
    # attributed to a real source)
    # ======================================================================
    dict(exploit=ExploitType.FABRICATED_SPECIFIC, expected="insufficient",
         claim="The CFO guided to a 14.5% FY2024 EBITDA margin.",
         evidence=(
             "On the Q4 earnings call, the CFO reiterated commitment to "
             "ongoing margin discipline but did not provide a specific FY2024 "
             "margin guidance."
         ),
         rationale="Real speaker, real topic, fabricated specific number."),
    dict(exploit=ExploitType.FABRICATED_SPECIFIC, expected="insufficient",
         claim="PwC's report cited a 22% probability of going-concern impairment.",
         evidence=(
             "PwC's FY2023 going-concern review concluded no material "
             "uncertainty exists, citing strong liquidity headroom and "
             "covenant compliance."
         ),
         rationale="Real source (PwC), real topic (going-concern), invented quant figure."),
]


def build_adversarial_cases() -> list[AdversarialCase]:
    """Return the deterministic list of adversarial cases. Same
    call → identical list every time."""
    return [
        _case(
            i + 1,
            exploit=spec["exploit"],
            claim=spec["claim"],
            evidence=spec["evidence"],
            expected=spec["expected"],
            rationale=spec["rationale"],
        )
        for i, spec in enumerate(_SPECS)
    ]


__all__ = ["AdversarialCase", "ExploitType", "build_adversarial_cases"]
