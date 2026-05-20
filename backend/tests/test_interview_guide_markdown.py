"""Phase 3 / Week 13 / Day 3 — interview guide markdown tests.

Eight tests per spec covering: three-section structure, Section A
gap_report wiring, Section B claim_id linkage, mode-specific Section
C content, metadata.question_count parity, priority assignment, and
the no-gap_report fallback.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.exports._base import ClaimCitation
from core.exports.interview_guide import InterviewGuideMarkdownExporter
from core.exports.interview_guide_builder import InterviewGuideBuilder


_BRANDING: dict[str, Any] = {"_firm_name": "Argus Demo Boutique"}


def _m_and_a_payload(*, with_gap_report: bool = True) -> dict[str, Any]:
    p: dict[str, Any] = {
        "mode": "m_and_a_diligence",
        "recommendation": "PROCEED WITH CONDITIONS",
        "key_reasons": [
            {"text": "Customer concentration is manageable given multi-year contracts",
             "claim_id": "claim_reason_1"},
            {"text": "EBITDA margin trajectory has been resilient through FY21–FY24",
             "claim_id": "claim_reason_2"},
            "Top-3 customer block carries multi-year SLAs",
        ],
        "risks": [
            {"text": "Working-capital seasonality compresses Q1 cash position",
             "claim_id": "claim_risk_1"},
            "Key-person dependency on the CTO",
        ],
        "synergy_estimate": {
            "revenue_synergies": [{"magnitude_gbp_m": 5.0}],
            "cost_synergies": [{"magnitude_gbp_m": 3.5}],
        },
        "deal_structure_implications": {
            "walk_away_triggers": ["Top customer churn before close"],
        },
        "_engagement_title": "TargetCo M&A diligence",
        "_target_name": "TargetCo Holdings",
        "_firm_name": "Argus Demo Boutique",
    }
    if with_gap_report:
        p["gap_report"] = {
            "title": "Some gaps remain",
            "missing_evidence": [
                "Scotland-specific competitive landscape",
                "Customer concentration calibration vs peers",
                "Walk-away trigger validation across leadership",
            ],
        }
    return p


def _growth_payload(*, with_gap_report: bool = True) -> dict[str, Any]:
    p: dict[str, Any] = {
        "mode": "growth_strategy",
        "recommendation": "EXPAND INTO UK MID-MARKET",
        "key_reasons": [
            {"text": "Adjacent capability set transfers without major hiring",
             "claim_id": "g_claim_1"},
        ],
        "risks": [
            {"text": "Incumbents will respond aggressively on price",
             "claim_id": "g_risk_1"},
        ],
        "competitive_landscape": {
            "competitors": [{"name": "Albright & Marsh"}],
        },
        "geography": "Scotland",
        "_engagement_title": "UK mid-market entry",
        "_target_name": "Newco",
        "_firm_name": "Argus Demo Boutique",
    }
    if with_gap_report:
        p["gap_report"] = {
            "missing_evidence": [
                "Scotland-specific customer behaviour",
                "Channel mix expectation",
            ],
        }
    return p


_CITATIONS = [
    ClaimCitation(claim_id="claim_reason_1", text="x", source_title="A", source_type="firm_library"),
]


# ---------------------------------------------------------------------------
# Test 1 — guide has three sections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guide_has_three_sections() -> None:
    result = await InterviewGuideMarkdownExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    md = result.file_bytes.decode("utf-8")
    assert "## Section A" in md
    assert "## Section B" in md
    assert "## Section C" in md
    # Closing notes also present.
    assert "## Closing notes" in md


# ---------------------------------------------------------------------------
# Test 2 — Section A pulls from gap_report missing_evidence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_a_pulls_from_gap_report() -> None:
    """Three gap items → three Section A questions (≤2 per item, capped
    at 7 total). Each gap text should appear in a Section A 'Why we're
    asking' or question line."""
    payload = _m_and_a_payload()
    builder = InterviewGuideBuilder(payload, _BRANDING, _CITATIONS)

    # Builder-level: one question per gap (we don't expand to 2 today).
    assert len(builder.section_a) == 3
    assert all(q.get("source") == "gap_report" for q in builder.section_a)
    # Each gap shows up in the 'why_asking' field of one of the questions.
    why_blob = " ".join(q.get("why_asking", "") for q in builder.section_a)
    assert "Scotland-specific competitive landscape" in why_blob
    assert "Customer concentration" in why_blob
    assert "Walk-away" in why_blob


@pytest.mark.asyncio
async def test_section_a_caps_at_seven_questions() -> None:
    payload = _m_and_a_payload()
    payload["gap_report"] = {
        "missing_evidence": [f"Gap topic {i}" for i in range(15)]
    }
    builder = InterviewGuideBuilder(payload, _BRANDING, _CITATIONS)
    assert len(builder.section_a) <= 7, "Section A spec cap is 7 questions"


# ---------------------------------------------------------------------------
# Test 3 — Section B questions carry claim_id linkage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_b_questions_linked_to_claim_ids() -> None:
    payload = _m_and_a_payload()
    builder = InterviewGuideBuilder(payload, _BRANDING, _CITATIONS)

    # Every Section B question maps to a reason or risk; the reasons +
    # risks in the fixture carry claim_ids, so at least 3 of the
    # Section B questions must have populated linked_claim_ids.
    with_links = [q for q in builder.section_b if q.get("linked_claim_ids")]
    assert len(with_links) >= 3, (
        f"expected ≥3 Section B questions with linked_claim_ids, "
        f"got {len(with_links)} of {len(builder.section_b)}"
    )
    # The cited_claim_ids property surfaces the union, used by the
    # artifact-row metadata.
    cited = set(builder.cited_claim_ids)
    assert "claim_reason_1" in cited
    assert "claim_reason_2" in cited
    assert "claim_risk_1" in cited

    # The markdown render carries the [claim_id: ...] inline marker for
    # Section B (and ONLY Section B — Section A is gap-derived, no claims).
    md = builder.build_markdown()
    assert "[claim_id: claim_reason_1]" in md
    # Section A questions don't carry the marker.
    sec_a_block = md.split("## Section B", 1)[0]
    assert "[claim_id:" not in sec_a_block


# ---------------------------------------------------------------------------
# Test 4 — M&A Section C includes integration questions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_and_a_section_c_includes_integration_questions() -> None:
    builder = InterviewGuideBuilder(_m_and_a_payload(), _BRANDING, _CITATIONS)
    sec_c_topics = [q.get("topic", "").lower() for q in builder.section_c]
    sec_c_texts = " ".join(q.get("text", "") for q in builder.section_c).lower()

    assert any("integration" in t for t in sec_c_topics), (
        f"M&A Section C missing integration topic: {sec_c_topics}"
    )
    assert any("synergy" in t for t in sec_c_topics), (
        f"M&A Section C missing synergy validation: {sec_c_topics}"
    )
    assert "walk-away" in sec_c_texts or "walk away" in sec_c_texts, (
        "M&A Section C should reference the walk-away trigger validation"
    )


# ---------------------------------------------------------------------------
# Test 5 — Growth Section C includes market dynamics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_growth_strategy_section_c_includes_market_dynamics() -> None:
    builder = InterviewGuideBuilder(_growth_payload(), _BRANDING, _CITATIONS)
    sec_c_topics = [q.get("topic", "").lower() for q in builder.section_c]
    sec_c_texts = " ".join(q.get("text", "") for q in builder.section_c).lower()

    # Mode dispatch worked.
    assert all(q.get("source") == "mode_specific" for q in builder.section_c)
    # Competitive response + channel mix questions are mandatory in growth_strategy.
    assert any("competitive response" in t for t in sec_c_topics)
    assert any("channel mix" in t for t in sec_c_topics)
    # Named competitor from payload propagates to the question text.
    assert "albright & marsh" in sec_c_texts, (
        f"named competitor missing from Section C: {sec_c_texts}"
    )
    # Geography phrase from payload propagates.
    assert "scotland" in sec_c_texts


# ---------------------------------------------------------------------------
# Test 6 — metadata.question_count matches actual rendered count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_question_count_in_metadata() -> None:
    result = await InterviewGuideMarkdownExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    declared = result.metadata["question_count"]
    md = result.file_bytes.decode("utf-8")

    # Count the rendered question anchors A1/A2/.../B1/.../C1/...
    import re as _re
    rendered = len(_re.findall(r"^### [ABC]\d+\.", md, flags=_re.MULTILINE))
    assert declared == rendered, (
        f"metadata.question_count={declared} but {rendered} rendered in markdown"
    )
    assert declared <= 15, "global cap is 15 questions"


# ---------------------------------------------------------------------------
# Test 7 — every question has a priority field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_question_priority_assigned() -> None:
    builder = InterviewGuideBuilder(_m_and_a_payload(), _BRANDING, _CITATIONS)
    valid = {"high", "medium", "low"}
    for sec_name, sec in (("A", builder.section_a), ("B", builder.section_b),
                          ("C", builder.section_c)):
        for i, q in enumerate(sec, start=1):
            p = (q.get("priority") or "").lower()
            assert p in valid, f"Section {sec_name} Q{i} priority invalid: {p!r}"


# ---------------------------------------------------------------------------
# Test 8 — no gap_report → Section A empty, Section B still populated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_gap_report_falls_back_to_recommendation_only_questions() -> None:
    builder = InterviewGuideBuilder(
        _m_and_a_payload(with_gap_report=False), _BRANDING, _CITATIONS,
    )
    assert builder.section_a == [], "Section A should be empty when no gap_report"
    # B + C should still produce questions.
    assert len(builder.section_b) >= 3
    assert len(builder.section_c) >= 3

    md = builder.build_markdown()
    # The honest fallback line lands in the markdown.
    assert "No critical evidence gaps identified" in md
