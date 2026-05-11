"""Phase 2 / Week 8 / Day 3 — framework schema validation tests.

One test class per framework. Per the spec, each schema must reject:
- empty required arrays
- items missing evidence_citations
- intensity / quadrant / category values outside the Literal set

Plus backward-compat coverage: WriterReportBase still parses
unchanged when ``frameworks`` is absent or ``None``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.writer.schemas import (
    ForceAssessment,
    FrameworksPayload,
    GeneralReportPayload,
    PortersFiveForcesAnalysis,
    TwoByTwoItem,
    TwoByTwoMatrix,
    ValueChainActivity,
    ValueChainAnalysis,
)


# ---------------------------------------------------------------------------
# TwoByTwoMatrix
# ---------------------------------------------------------------------------


def _valid_two_by_two_kwargs(**overrides):
    kw = dict(
        title="Target screen — TargetCo segments",
        x_axis_label="Strategic fit",
        x_axis_low_label="Low",
        x_axis_high_label="High",
        y_axis_label="Ease of integration",
        y_axis_low_label="Low",
        y_axis_high_label="High",
        items=[
            {
                "name": "Facilities Maintenance",
                "quadrant": "top_right",
                "rationale": "Core synergy with existing service lines + low cultural distance.",
                "evidence_citations": ["c1"],
            },
            {
                "name": "Mechanical Services",
                "quadrant": "bottom_left",
                "rationale": "Weak strategic fit and difficult system integration.",
                "evidence_citations": ["c2"],
            },
            {
                "name": "Compliance Services",
                "quadrant": "top_left",
                "rationale": "Strong cultural alignment but limited cross-sell potential.",
                "evidence_citations": ["c3"],
            },
            {
                "name": "International Expansion",
                "quadrant": "bottom_right",
                "rationale": "High strategic fit but operationally complex post-close.",
                "evidence_citations": ["c4"],
            },
        ],
        interpretation="Cluster sits at top-right; Mechanical is the weakest tile and a candidate for divestment.",
    )
    kw.update(overrides)
    return kw


def test_two_by_two_valid_payload_parses() -> None:
    m = TwoByTwoMatrix(**_valid_two_by_two_kwargs())
    assert m.title.startswith("Target screen")
    # W8/D5 iterate-4: min_length is back to 2; fixture still uses 4
    # items (richer demo shape), but the schema-floor check below
    # confirms the floor is the soft 2, not the over-strict 4.
    assert len(m.items) == 4


def test_two_by_two_rejects_empty_items() -> None:
    with pytest.raises(ValidationError) as exc:
        TwoByTwoMatrix(**_valid_two_by_two_kwargs(items=[]))
    assert "items" in str(exc.value)


def test_two_by_two_accepts_two_items() -> None:
    """W8/D5 iterate-4: min_length=2 (reverted from over-strict 4). A
    2-item 2x2 should validate; the prompt aims for 4-6 as a soft
    target, but the schema floor is 2."""
    two_items = [
        {
            "name": f"Tile {i}",
            "quadrant": "top_left",
            "rationale": "Long enough rationale to clear the twenty char minimum.",
            "evidence_citations": [f"c{i}"],
        }
        for i in range(2)
    ]
    m = TwoByTwoMatrix(**_valid_two_by_two_kwargs(items=two_items))
    assert len(m.items) == 2


def test_two_by_two_rejects_more_than_12_items() -> None:
    too_many = [
        {
            "name": f"Item {i}",
            "quadrant": "top_left",
            "rationale": "Rationale paragraph long enough to clear min length.",
            "evidence_citations": [f"c{i}"],
        }
        for i in range(13)
    ]
    with pytest.raises(ValidationError):
        TwoByTwoMatrix(**_valid_two_by_two_kwargs(items=too_many))


def test_two_by_two_item_rejects_missing_evidence_citations() -> None:
    with pytest.raises(ValidationError) as exc:
        TwoByTwoItem(
            name="Test item",
            quadrant="top_left",
            rationale="Rationale long enough to clear the twenty char minimum.",
            evidence_citations=[],
        )
    assert "evidence_citations" in str(exc.value)


def test_two_by_two_item_rejects_invalid_quadrant() -> None:
    with pytest.raises(ValidationError) as exc:
        TwoByTwoItem(
            name="Test",
            quadrant="middle",  # not in Literal set
            rationale="Rationale long enough to clear the twenty char minimum.",
            evidence_citations=["c1"],
        )
    assert "quadrant" in str(exc.value)


# ---------------------------------------------------------------------------
# PortersFiveForcesAnalysis
# ---------------------------------------------------------------------------


def _valid_force(**overrides) -> dict:
    base = dict(
        intensity="moderate",
        rationale="Three large players hold 62% share; switching costs are non-trivial but not lock-in.",
        key_drivers=["High fixed costs", "Slow demand growth", "Moderate differentiation"],
        evidence_citations=["c1"],
    )
    base.update(overrides)
    return base


def _valid_porters_kwargs(**overrides) -> dict:
    base = dict(
        market_definition="UK industrial facilities maintenance — listed + private firms above £50m revenue.",
        rivalry=_valid_force(),
        supplier_power=_valid_force(intensity="low"),
        buyer_power=_valid_force(intensity="high"),
        substitute_threat=_valid_force(intensity="low"),
        new_entrant_threat=_valid_force(intensity="moderate"),
        overall_attractiveness="moderate",
        overall_rationale="Buyer power offsets supplier weakness; rivalry capped by structural costs.",
    )
    base.update(overrides)
    return base


def test_porters_valid_payload_parses() -> None:
    p = PortersFiveForcesAnalysis(**_valid_porters_kwargs())
    assert p.overall_attractiveness == "moderate"
    assert p.rivalry.intensity == "moderate"


def test_porters_force_rejects_invalid_intensity() -> None:
    with pytest.raises(ValidationError) as exc:
        ForceAssessment(**_valid_force(intensity="very_high"))
    assert "intensity" in str(exc.value)


def test_porters_force_rejects_fewer_than_2_key_drivers() -> None:
    with pytest.raises(ValidationError) as exc:
        ForceAssessment(**_valid_force(key_drivers=["Only one"]))
    assert "key_drivers" in str(exc.value)


def test_porters_force_rejects_empty_evidence_citations() -> None:
    with pytest.raises(ValidationError) as exc:
        ForceAssessment(**_valid_force(evidence_citations=[]))
    assert "evidence_citations" in str(exc.value)


def test_porters_rejects_missing_market_definition() -> None:
    with pytest.raises(ValidationError):
        PortersFiveForcesAnalysis(**_valid_porters_kwargs(market_definition=""))


# ---------------------------------------------------------------------------
# ValueChainAnalysis
# ---------------------------------------------------------------------------


def _valid_activity(**overrides) -> dict:
    base = dict(
        name="Operations",
        category="primary",
        canonical_step="operations",
        assessment="Plant utilisation runs 84% versus 71% industry median; lean program is bedded in.",
        competitive_implication="Cost-per-unit advantage of ~3% vs nearest comparable.",
        evidence_citations=["c1"],
    )
    base.update(overrides)
    return base


def _valid_value_chain_kwargs(**overrides) -> dict:
    base = dict(
        business_context="UK contract services arm — facilities maintenance + mechanical services lines.",
        activities=[
            _valid_activity(),
            _valid_activity(name="Procurement", category="support", canonical_step="procurement"),
            _valid_activity(name="Service", category="primary", canonical_step="service"),
            _valid_activity(
                name="Tech Development",
                category="support",
                canonical_step="technology_development",
            ),
        ],
        overall_thesis="Wins on operations + procurement; technology gap is the strategic bet for the buyer.",
    )
    base.update(overrides)
    return base


def test_value_chain_valid_payload_parses() -> None:
    vc = ValueChainAnalysis(**_valid_value_chain_kwargs())
    assert len(vc.activities) == 4


def test_value_chain_rejects_fewer_than_4_activities() -> None:
    short = _valid_value_chain_kwargs(activities=[_valid_activity()] * 3)
    with pytest.raises(ValidationError) as exc:
        ValueChainAnalysis(**short)
    assert "activities" in str(exc.value)


def test_value_chain_activity_rejects_invalid_category() -> None:
    with pytest.raises(ValidationError) as exc:
        ValueChainActivity(**_valid_activity(category="other"))
    assert "category" in str(exc.value)


def test_value_chain_activity_rejects_invalid_canonical_step() -> None:
    with pytest.raises(ValidationError) as exc:
        ValueChainActivity(**_valid_activity(canonical_step="random_step"))
    assert "canonical_step" in str(exc.value)


def test_value_chain_activity_rejects_missing_evidence_citations() -> None:
    with pytest.raises(ValidationError) as exc:
        ValueChainActivity(**_valid_activity(evidence_citations=[]))
    assert "evidence_citations" in str(exc.value)


# ---------------------------------------------------------------------------
# Backward compat
# ---------------------------------------------------------------------------


def _minimal_base_kwargs() -> dict:
    return dict(
        mode="general",
        recommendation="x",
        confidence_level="High",
        summary="y",
        key_reasons=["a", "b", "c", "d"],
        risks=["r"],
        counterarguments=["c"],
        next_steps=["n1", "n2", "n3", "n4", "n5"],
        sources=[{"title": "t", "type": "k"}],
    )


def test_writer_report_base_without_frameworks_parses_unchanged() -> None:
    """Existing payloads (frameworks key absent) still validate; the
    new optional field defaults to None."""
    payload = GeneralReportPayload(**_minimal_base_kwargs())
    assert payload.frameworks is None


def test_writer_report_base_accepts_partial_frameworks() -> None:
    """A payload with only one of the three framework slots populated
    is valid; the others stay None."""
    fw = FrameworksPayload(two_by_two=TwoByTwoMatrix(**_valid_two_by_two_kwargs()))
    payload = GeneralReportPayload(**_minimal_base_kwargs(), frameworks=fw)
    assert payload.frameworks is not None
    assert payload.frameworks.two_by_two is not None
    assert payload.frameworks.porters_five_forces is None
    assert payload.frameworks.value_chain is None


def test_writer_report_base_accepts_all_three_frameworks() -> None:
    fw = FrameworksPayload(
        two_by_two=TwoByTwoMatrix(**_valid_two_by_two_kwargs()),
        porters_five_forces=PortersFiveForcesAnalysis(**_valid_porters_kwargs()),
        value_chain=ValueChainAnalysis(**_valid_value_chain_kwargs()),
    )
    payload = GeneralReportPayload(**_minimal_base_kwargs(), frameworks=fw)
    assert all(
        getattr(payload.frameworks, name) is not None
        for name in ("two_by_two", "porters_five_forces", "value_chain")
    )
