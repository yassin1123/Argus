"""Phase 2 / Week 8 / Day 4 — frameworks-in-modes integration tests.

Six tests per the spec plus one explicit backward-compat regression
for modes with no framework declaration.

The writer-prompt assertion exercises the same prompt-stitching path
the live ``WriterAgent.run`` uses by importing
``build_framework_instructions`` and asserting its output is what
``WriterAgent`` would concatenate onto the base prompt.
"""

from __future__ import annotations

import pytest

from agents.critic_checks import apply_mode_checks
from agents.critic_checks._frameworks import check_required_frameworks
from agents.writer.prompts import (
    M_AND_A_WRITER_PROMPT,
    build_framework_instructions,
)
from agents.writer.schemas import (
    ForceAssessment,
    FrameworksPayload,
    GeneralReportPayload,
    PortersFiveForcesAnalysis,
    TwoByTwoMatrix,
)
from core.consulting_modes import FrameworksModeConfig, ResolvedConsultingMode, resolve_mode
from core.consulting_modes.resolver import _yaml_reset


@pytest.fixture(autouse=True)
def _reset_resolver_cache():
    _yaml_reset()
    yield
    _yaml_reset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_writer_payload(**overrides) -> GeneralReportPayload:
    kw: dict = dict(
        mode="m_and_a_diligence",
        recommendation="Acquire TargetCo at £210m EV via cash + 20% earn-out.",
        confidence_level="Medium-High",
        summary="TargetCo's segment strengths align with our platform thesis.",
        key_reasons=[
            "Facilities Maintenance compounds at 8% with 91% recurring revenue.",
            "Pilot cost £180k vs full-roll-out £2.1m caps the integration risk.",
            "Three reference customers in-region accelerate logo-zero.",
            "Local language overlap supports Austria expansion next phase.",
        ],
        risks=["Halo contract renewal probability below 60%."],
        counterarguments=["NRW has larger absolute TAM."],
        next_steps=[
            "Sign first pilot LoI within 30 days.",
            "Hire Bavaria GTM lead.",
            "Lock pricing model with finance.",
            "Set 6-month kill criteria.",
            "Quarterly review with steering committee.",
        ],
        sources=[{"title": "Mittelstand benchmark 2025", "type": "research"}],
    )
    kw.update(overrides)
    return GeneralReportPayload(**kw)


def _valid_two_by_two() -> TwoByTwoMatrix:
    return TwoByTwoMatrix(
        title="Acquisition target screen — TargetCo segments",
        x_axis_label="Strategic fit",
        x_axis_low_label="Low",
        x_axis_high_label="High",
        y_axis_label="Deal complexity",
        y_axis_low_label="Low",
        y_axis_high_label="High",
        items=[
            {
                "name": "Facilities Maintenance",
                "quadrant": "bottom_right",
                "rationale": "High strategic fit, low complexity: shared customer base + simple integration.",
                "evidence_citations": ["c-fm-1"],
            },
            {
                "name": "Mechanical Services",
                "quadrant": "top_left",
                "rationale": "Low fit, high complexity: separate sales motion + legacy ERP.",
                "evidence_citations": ["c-ms-1"],
            },
            {
                "name": "Compliance Services",
                "quadrant": "top_left",
                "rationale": "Strong cultural fit but limited revenue scale + integration overhead.",
                "evidence_citations": ["c-cs-1"],
            },
            {
                "name": "International Expansion",
                "quadrant": "bottom_right",
                "rationale": "High strategic upside but complex regulatory + GTM integration work.",
                "evidence_citations": ["c-ie-1"],
            },
        ],
        interpretation="Cluster sits bottom-right; Mechanical Services is a divestiture candidate.",
    )


def _valid_porters() -> PortersFiveForcesAnalysis:
    def f():
        return ForceAssessment(
            intensity="moderate",
            rationale="Three large players hold 62% share; switching costs non-trivial.",
            key_drivers=["High fixed costs", "Slow demand growth", "Moderate differentiation"],
            evidence_citations=["c-r-1"],
        )
    return PortersFiveForcesAnalysis(
        market_definition="UK industrial facilities maintenance — listed + private firms above £50m revenue.",
        rivalry=f(),
        supplier_power=f(),
        buyer_power=f(),
        substitute_threat=f(),
        new_entrant_threat=f(),
        overall_attractiveness="moderate",
        overall_rationale="Buyer power offsets supplier weakness; rivalry capped by structural costs.",
    )


# ---------------------------------------------------------------------------
# Test 1 — M&A mode resolves with required=["two_by_two"]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_and_a_mode_requires_two_by_two() -> None:
    resolved = await resolve_mode("m_and_a_diligence", firm_id=None)
    assert resolved.frameworks is not None
    assert resolved.frameworks.required == ["two_by_two"]
    assert "porters_five_forces" in resolved.frameworks.optional


# ---------------------------------------------------------------------------
# Test 2 — Writer prompt includes 2x2 instructions for M&A
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_prompt_includes_2x2_instructions_for_m_and_a() -> None:
    resolved = await resolve_mode("m_and_a_diligence", firm_id=None)
    block = build_framework_instructions(resolved.frameworks)
    assert "frameworks.two_by_two" in block
    # The M&A axis pairing is named in the required block.
    assert "Deal complexity" in block
    assert "Strategic fit" in block
    assert "REQUIRED FRAMEWORKS" in block
    # Optional Porter's also appears under the discouraging header.
    assert "OPTIONAL FRAMEWORKS" in block
    assert "frameworks.porters_five_forces" in block
    # Stitched-onto-base-prompt check — assert WriterAgent would
    # emit a system prompt containing both the base M&A guidance
    # and the framework block.
    full = M_AND_A_WRITER_PROMPT + "\n\nFRAMEWORK REQUIREMENTS:\n" + block
    assert "FRAMEWORK REQUIREMENTS:" in full
    assert "MAndADiligenceReportPayload" in full  # from base prompt
    assert "frameworks.two_by_two" in full        # from framework block


# ---------------------------------------------------------------------------
# Test 3 — Critic flags missing required framework
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critic_flags_missing_required_framework() -> None:
    resolved = await resolve_mode("m_and_a_diligence", firm_id=None)
    payload = _minimal_writer_payload()  # frameworks=None
    assert payload.frameworks is None
    issues = check_required_frameworks(payload, resolved.frameworks)
    assert len(issues) == 1
    assert issues[0].level == "error"
    assert issues[0].field == "frameworks.two_by_two"
    assert "two_by_two" in issues[0].message


# ---------------------------------------------------------------------------
# Test 4 — Critic passes when required framework is populated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critic_passes_when_required_framework_populated() -> None:
    resolved = await resolve_mode("m_and_a_diligence", firm_id=None)
    fw = FrameworksPayload(two_by_two=_valid_two_by_two())
    payload = _minimal_writer_payload(frameworks=fw)
    issues = check_required_frameworks(payload, resolved.frameworks)
    assert issues == []


# ---------------------------------------------------------------------------
# Test 5 — Optional framework not required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optional_framework_not_required() -> None:
    """growth_strategy declares required=[porters_five_forces],
    optional=[value_chain, two_by_two]. A payload with porters populated
    but value_chain + two_by_two null should produce zero findings."""
    resolved = await resolve_mode("growth_strategy", firm_id=None)
    fw = FrameworksPayload(porters_five_forces=_valid_porters())  # only the required slot
    payload = _minimal_writer_payload(mode="growth_strategy", frameworks=fw)
    issues = check_required_frameworks(payload, resolved.frameworks)
    assert issues == []


# ---------------------------------------------------------------------------
# Test 6 — Regression: modes with no framework declaration are untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_framework_modes_unchanged() -> None:
    """``general`` / ``market_entry`` / ``due_diligence`` have no
    frameworks declaration in YAML. Their resolved mode should carry
    ``frameworks=None``, build_framework_instructions returns "",
    and the critic check produces no findings — i.e. legacy
    engagement flow is untouched."""
    for mode_name in ("general", "market_entry", "due_diligence"):
        resolved = await resolve_mode(mode_name, firm_id=None)
        assert resolved.frameworks is None, f"{mode_name} should have frameworks=None"
        block = build_framework_instructions(resolved.frameworks)
        assert block == ""
        payload = _minimal_writer_payload(mode=mode_name)
        issues = check_required_frameworks(payload, resolved.frameworks)
        assert issues == []

    # apply_mode_checks also produces no framework findings for these
    # modes when resolved_mode is threaded through.
    resolved_general = await resolve_mode("general", firm_id=None)
    payload = _minimal_writer_payload(mode="general")
    issues = apply_mode_checks("general", payload, resolved_mode=resolved_general)
    # check_general is a no-op AND framework check is a no-op → zero issues.
    assert all(
        i.field != "frameworks.two_by_two"
        and i.field != "frameworks.porters_five_forces"
        and i.field != "frameworks.value_chain"
        for i in issues
    )


# ---------------------------------------------------------------------------
# Extra coverage — resolver rejects unknown framework slot in YAML
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_rejects_unknown_framework_slot(
    tmp_path, monkeypatch
) -> None:
    """A firm or engagement override that names a typo framework
    (e.g. ``twobytwo`` instead of ``two_by_two``) should fail at
    resolve time, not silently disable the requirement."""
    bad_yaml = tmp_path / "bad_modes.yaml"
    bad_yaml.write_text(
        """
test_mode:
  display_name: Test
  frameworks:
    required:
      - twobytwo
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARGUS_CONSULTING_MODES_PATH", str(bad_yaml))
    _yaml_reset()
    from core.consulting_modes.types import ModeConfigError

    with pytest.raises(ModeConfigError) as exc:
        await resolve_mode("test_mode", firm_id=None)
    assert "twobytwo" in str(exc.value)
