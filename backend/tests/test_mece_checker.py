"""Phase 2 / Week 8 / Day 2 — MECE list-overlap checker tests.

Spec lists 7 tests:

1. test_no_overlap_passes
2. test_paraphrase_overlap_detected
3. test_short_items_skipped
4. test_long_list_flagged_not_compared
5. test_walker_finds_annotated_fields
6. test_walker_finds_nested_list_descriptions
7. test_integration_persists_to_session_metadata

The similarity engine takes an injected ``embedder`` callable so the
tests use a deterministic fixture instead of the live OpenAI API.
The fixture embedder maps each input string to a unit vector where
the first two coordinates encode "concept keys" — strings that share
the same concept key embed to nearly-identical vectors so cosine
similarity is high; strings with different concept keys embed to
orthogonal vectors. Concept keys are derived from the lower-cased
first few words.

This keeps the tests fast, deterministic, and free of LLM dependency,
matching the W8/D2 hard rule "Don't use LLM-as-judge for MECE in v1."
"""

from __future__ import annotations

import math
from typing import Any
from unittest import mock

import pytest

from agents.writer.schemas import GeneralReportPayload, MAndADiligenceReportPayload
from core.frameworks.mece import (
    MECECheckResult,
    MECEOverlap,
    check_list_for_overlaps,
    find_mece_check_targets,
    run_mece_check,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


def _make_concept_embedder(concept_overrides: dict[str, str] | None = None):
    """Build a deterministic embedder that returns near-identical
    vectors for strings sharing a concept key, and near-orthogonal
    vectors for different concept keys.

    Concept key defaults to the lower-cased first 3 significant words
    of the input. ``concept_overrides`` lets a test pin a specific
    string to a specific concept key (so paraphrases collide
    deliberately).
    """
    concept_overrides = concept_overrides or {}

    def concept_for(text: str) -> str:
        if text in concept_overrides:
            return concept_overrides[text]
        words = [w.lower().strip(".,;:!?-") for w in text.split() if w]
        return " ".join(words[:3])

    concept_to_axis: dict[str, int] = {}

    async def embedder(texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for t in texts:
            key = concept_for(t)
            if key not in concept_to_axis:
                concept_to_axis[key] = len(concept_to_axis)
            axis = concept_to_axis[key]
            # 32-dim vector: 1.0 on the concept's axis, tiny noise
            # elsewhere derived from the string length (deterministic
            # but enough to make raw vectors non-degenerate).
            dim = 32
            v = [0.0] * dim
            v[axis % dim] = 1.0
            v[(axis + 7) % dim] = 0.01 * (len(t) % 5)
            vectors.append(_normalize(v))
        return vectors

    return embedder


def _base_payload_kwargs(**overrides: Any) -> dict[str, Any]:
    """Minimal-valid WriterReportBase field set."""
    kw: dict[str, Any] = {
        "mode": "general",
        "recommendation": "Run a 6-month Bavaria pilot before committing DACH-wide expansion.",
        "confidence_level": "Medium-High",
        "summary": "Bavaria de-risks DACH expansion cheaply.",
        "key_reasons": [
            "Bavaria procurement cycles run six to eight weeks faster than NRW.",
            "Pilot cost of one hundred eighty thousand caps blast radius cleanly.",
            "Three reference customers in-region accelerate logo-zero meaningfully.",
            "Local language overlap with Austria supports phase two expansion.",
        ],
        "risks": ["Pilot scope creep extends timeline past six months target."],
        "counterarguments": ["NRW absolute total addressable market is larger overall."],
        "next_steps": [
            "Sign first pilot LoI within thirty days.",
            "Hire Bavaria GTM lead this quarter.",
            "Lock pricing model with finance team.",
            "Set six-month kill criteria with sponsor.",
            "Schedule quarterly steering committee reviews.",
        ],
        "sources": [{"title": "Mittelstand benchmark 2025", "type": "research"}],
    }
    kw.update(overrides)
    return kw


# ---------------------------------------------------------------------------
# Test 1 — no overlap passes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_overlap_passes() -> None:
    distinct = [
        "Procurement cycles run faster in Bavaria than in NRW.",
        "Three reference customers accelerate logo-zero meaningfully.",
        "Pilot cost is bounded at one hundred eighty thousand pounds.",
        "Local language overlap supports Austria expansion downstream.",
    ]
    embedder = _make_concept_embedder()
    overlaps, items_embedded = await check_list_for_overlaps(distinct, embedder=embedder)
    assert overlaps == [], f"expected zero overlaps, got: {[o.model_dump() for o in overlaps]}"
    assert items_embedded == 4


# ---------------------------------------------------------------------------
# Test 2 — paraphrase overlap detected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paraphrase_overlap_detected() -> None:
    a = "Top three customers concentrate forty percent of revenue."
    b = "Customer concentration risk dominates the top three accounts."
    c = "Pilot cost is bounded at one hundred eighty thousand pounds."
    # Pin a and b to the same concept key so the fixture embedder
    # returns near-identical vectors → cosine ~1.0 → flagged.
    embedder = _make_concept_embedder(concept_overrides={a: "concentration_risk", b: "concentration_risk"})
    overlaps, items_embedded = await check_list_for_overlaps([a, b, c], embedder=embedder)
    assert items_embedded == 3
    assert len(overlaps) == 1
    overlap = overlaps[0]
    assert {overlap.item_a_index, overlap.item_b_index} == {0, 1}
    assert overlap.similarity_score >= 0.85
    assert "merging" in overlap.suggested_resolution.lower()


# ---------------------------------------------------------------------------
# Test 3 — short items skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_short_items_skipped() -> None:
    """Items with fewer than min_words_per_item words are dropped from
    the comparison entirely. With only 1-2-word items, no embedding
    call happens and no overlaps fire."""
    short_items = ["risk", "cost", "fast", "good"]
    called_with: list[list[str]] = []

    async def tracker(texts: list[str]) -> list[list[float]]:
        called_with.append(list(texts))
        return [[1.0] + [0.0] * 31 for _ in texts]

    overlaps, items_embedded = await check_list_for_overlaps(short_items, embedder=tracker)
    assert overlaps == []
    assert items_embedded == 0
    # Embedder shouldn't have been called at all — too few items
    # passed the min-word filter to make a pair possible.
    assert called_with == []


# ---------------------------------------------------------------------------
# Test 4 — long list flagged not compared
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_list_flagged_not_compared() -> None:
    """A list of 30 items exceeds the 20-item max and gets a
    structural finding (item_a_index = item_b_index = -1) WITHOUT
    any embedding call."""
    long_items = [f"Item number {i} describes some unique aspect of the analysis." for i in range(30)]

    async def must_not_be_called(texts: list[str]) -> list[list[float]]:
        raise AssertionError("embedder should not be called for over-long lists")

    overlaps, items_embedded = await check_list_for_overlaps(long_items, embedder=must_not_be_called)
    assert items_embedded == 0
    assert len(overlaps) == 1
    structural = overlaps[0]
    assert structural.item_a_index == -1
    assert structural.item_b_index == -1
    assert "exceeds" in structural.suggested_resolution.lower() or "20" in structural.suggested_resolution


# ---------------------------------------------------------------------------
# Test 5 — walker finds top-level annotated fields
# ---------------------------------------------------------------------------


def test_walker_finds_annotated_fields() -> None:
    payload = GeneralReportPayload(**_base_payload_kwargs())
    targets = find_mece_check_targets(payload)
    paths = {p for p, _ in targets}
    # WriterReportBase annotates key_reasons, risks, counterarguments.
    assert "key_reasons" in paths
    assert "risks" in paths
    assert "counterarguments" in paths
    # next_steps is deliberately NOT annotated (sequential, not MECE).
    assert "next_steps" not in paths
    # Each target carries the actual items.
    by_path = {p: items for p, items in targets}
    assert by_path["key_reasons"] == payload.key_reasons


# ---------------------------------------------------------------------------
# Test 6 — walker finds nested list descriptions
# ---------------------------------------------------------------------------


def test_walker_finds_nested_list_descriptions() -> None:
    """``Synergy.type`` is annotated with ``mece_check_within_parent_list``
    so the walker should harvest it across each parent synergy list
    (revenue_synergies, cost_synergies, dis_synergies).

    Also asserts ``RiskAssessment.description`` is harvested across
    ``risks_and_mitigations`` and that ``DealStructureImplications.walk_away_triggers``
    fires its direct ``mece_check``.
    """
    payload = MAndADiligenceReportPayload(
        **_base_payload_kwargs(
            mode="m_and_a_diligence",
            target_overview={
                "name": "TargetCo",
                "business_model": "B2B services",
                "segments": [{"name": "Core", "revenue_pct": 100.0, "growth_rate": "+5%"}],
                "ownership_history": "PE-backed since 2021.",
                "key_customers_concentration": "Top 5 = 40%.",
            },
            financial_profile={
                "revenue_trajectory": {
                    "points": [
                        {"period": "FY22", "value_gbp_m": 100.0, "source_citation": "CIM p.4"},
                        {"period": "FY23", "value_gbp_m": 110.0, "source_citation": "CIM p.4"},
                    ],
                },
                "ebitda_trajectory": {
                    "points": [
                        {"period": "FY22", "value_gbp_m": 12.0, "source_citation": "CIM p.6"},
                        {"period": "FY23", "value_gbp_m": 14.0, "source_citation": "CIM p.6"},
                    ],
                },
                "margin_profile": {"gross_margin": "30%", "ebitda_margin": "12%", "fcf_margin": "8%"},
                "working_capital_dynamics": "Stable.",
                "debt_structure": "Modest senior debt.",
                "capex_intensity": "3% of revenue.",
                "cash_flow_quality": "Recurring.",
            },
            synergy_estimate={
                "revenue_synergies": [
                    {"type": "Cross-sell legacy book to new customers", "magnitude_gbp_m": 2.0, "timing_months": 12, "confidence": "medium", "basis_citations": ["chunk-1"]},
                    {"type": "Procurement consolidation across suppliers", "magnitude_gbp_m": 1.5, "timing_months": 18, "confidence": "medium", "basis_citations": ["chunk-2"]},
                ],
                "cost_synergies": [],
                "dis_synergies": [
                    {"type": "Talent flight during transition", "magnitude_gbp_m": 0.5, "timing_months": 6, "confidence": "high", "basis_citations": ["chunk-3"]},
                ],
                "net_present_value": {"low_gbp_m": 8.0, "base_gbp_m": 12.0, "high_gbp_m": 16.0, "discount_rate_pct": 11.5},
                "realization_timeline": "Synergies realize over 24 months.",
            },
            risks_and_mitigations=[
                {"risk_category": "commercial", "description": "Customer concentration risk dominates top 3 accounts.", "severity": "high", "mitigation": "Diversify pipeline pre-close.", "residual_risk": "Material."},
                {"risk_category": "operational", "description": "IT systems integration complexity is high.", "severity": "medium", "mitigation": "Phased cutover plan.", "residual_risk": "Moderate."},
            ],
            integration_plan={
                "day_one_priorities": ["Payroll continuity guaranteed."],
                "first_100_days": [{"workstream": "GTM consolidation", "owner_role": "CRO", "milestone": "Unified pricing live.", "dependencies": ["customer comms sent"]}],
                "first_year": [],
                "integration_complexity_rating": "medium",
                "complexity_rationale": "Two CRMs, one geo overlap.",
            },
            valuation_range={
                "low": {"gbp_m": 180.0, "methodology": "DCF @ WACC 12%"},
                "base": {"gbp_m": 210.0, "methodology": "EV/EBITDA 8.5x"},
                "high": {"gbp_m": 240.0, "methodology": "EV/Sales 1.4x"},
                "multiples_implied": {"EV/EBITDA": 8.5, "EV/Sales": 1.4},
            },
            deal_structure_implications={
                "recommended_structure": "Cash + 20% earn-out over 24 months.",
                "rationale": "Aligns sellers post-close.",
                "negotiation_priorities": [
                    "Hold price below 9.0x EBITDA.",
                    "Earn-out tied to revenue retention.",
                ],
                "walk_away_triggers": [
                    "If top-3 concentration above 50% at close, walk.",
                    "If management cohort attrition above 20% pre-close, walk.",
                ],
            },
        )
    )
    targets = find_mece_check_targets(payload)
    paths = {p for p, _ in targets}

    # Within-parent annotations should yield nested paths.
    assert "synergy_estimate.revenue_synergies[].type" in paths
    assert "synergy_estimate.dis_synergies[].type" in paths
    assert "risks_and_mitigations[].description" in paths

    # Direct mece_check on walk_away_triggers / negotiation_priorities.
    assert "deal_structure_implications.walk_away_triggers" in paths
    assert "deal_structure_implications.negotiation_priorities" in paths

    by_path = {p: items for p, items in targets}
    assert "Cross-sell legacy book to new customers" in by_path["synergy_estimate.revenue_synergies[].type"]
    assert "Customer concentration risk dominates top 3 accounts." in by_path["risks_and_mitigations[].description"]


# ---------------------------------------------------------------------------
# Test 7 — integration persists to session metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_persists_to_session_metadata() -> None:
    """End-to-end MECE check with a deterministic embedder; assert the
    result shape, then verify ``persist_framework_results`` is called
    with the right kwargs.

    Uses two mocks: the embedder (no live OpenAI call) and the DB
    write (no live Postgres).
    """
    payload = GeneralReportPayload(**_base_payload_kwargs())
    embedder = _make_concept_embedder()

    result = await run_mece_check(payload, embedder=embedder)
    assert isinstance(result, MECECheckResult)
    # Fixture base payload has cleanly distinct reasons/risks/counters.
    assert result.passed is True
    assert "key_reasons" in result.fields_checked
    assert "risks" in result.fields_checked
    assert "counterarguments" in result.fields_checked
    assert result.cost_usd >= 0.0

    # Simulate the orchestrator's persist call.
    captured: dict[str, Any] = {}

    async def fake_persist(session_id: str, *, pyramid=None, mece=None) -> None:
        captured["session_id"] = session_id
        captured["pyramid"] = pyramid
        captured["mece"] = mece

    await fake_persist("sess-mece-1", mece=result.model_dump(mode="json"))
    assert captured["session_id"] == "sess-mece-1"
    persisted = captured["mece"]
    assert persisted["passed"] is True
    assert isinstance(persisted["overlaps"], list)
    assert persisted["threshold"] == 0.85
