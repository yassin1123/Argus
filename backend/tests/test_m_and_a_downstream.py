"""Phase 2 / Week 7 / Iterate — downstream-path validation.

Hand-build a valid M&A payload (no LLM in the loop), run it through the
critic checks + serialisation surface that the frontend renderer
consumes, confirm both ends are healthy. If any of these three tests
fail, fix the broken path BEFORE spending another LLM run on Step 5.
"""

from __future__ import annotations

import pytest

from agents.critic_checks import apply_mode_checks
from agents.writer.schemas import MAndADiligenceReportPayload
from tests.fixtures.m_and_a import build_minimal_valid_m_and_a_payload


def test_hand_built_payload_passes_critic_checks() -> None:
    """A clean M&A payload should produce zero critic-checks issues at
    error / warning level. Day-3 critic checks fire on monotonic
    valuation, distinct methodologies, non-empty dis-synergies, and
    falsifiable walk-aways — the fixture honours all of them."""
    payload = build_minimal_valid_m_and_a_payload()
    issues = apply_mode_checks("m_and_a_diligence", payload)
    error_or_warning = [i for i in issues if i.level in ("error", "warning")]
    assert not error_or_warning, (
        "expected zero error/warning issues on a clean payload, got: "
        + "; ".join(f"[{i.level}] {i.field}: {i.message}" for i in error_or_warning)
    )


def test_hand_built_payload_serializes_to_renderable_json() -> None:
    """Confirm the schema's JSON shape matches what the frontend
    MemoRenderer dispatcher expects (mode == "m_and_a_diligence" + the
    seven structured top-level sections all populated)."""
    payload = build_minimal_valid_m_and_a_payload()
    json_out = payload.model_dump(mode="json")
    assert json_out["mode"] == "m_and_a_diligence"
    for field in (
        "target_overview",
        "financial_profile",
        "synergy_estimate",
        "risks_and_mitigations",
        "integration_plan",
        "valuation_range",
        "deal_structure_implications",
    ):
        assert field in json_out, f"missing top-level field: {field}"
        # Each is either a populated dict or a non-empty list.
        v = json_out[field]
        assert v, f"empty top-level field: {field}"

    # Nested sanity: the multiples_implied at base case must include
    # both EV/EBITDA and EV/Sales (Day-1 schema validator) so the
    # ValuationRangeTable renderer has data to draw.
    multiples = (json_out.get("valuation_range") or {}).get("multiples_implied") or {}
    keys_lower = {k.lower() for k in multiples.keys()}
    assert "ev/ebitda" in keys_lower and "ev/sales" in keys_lower

    # Round-trip parse — what the frontend would receive after JSONB
    # deserialisation should validate cleanly.
    re_parsed = MAndADiligenceReportPayload.model_validate(json_out)
    assert re_parsed.target_overview.name == payload.target_overview.name


def test_critic_flags_non_monotonic_valuation() -> None:
    """Sanity-check that the Day-3 critic still rejects bad payloads —
    inverting low/high should produce a warning issue."""
    payload = build_minimal_valid_m_and_a_payload()
    bad = payload.model_dump(mode="json")
    bad["valuation_range"]["low"]["gbp_m"] = 999.0
    bad["valuation_range"]["high"]["gbp_m"] = 100.0
    issues = apply_mode_checks("m_and_a_diligence", bad)
    flagged = [i for i in issues if i.field == "valuation_range"]
    assert flagged, "expected a valuation_range issue on inverted low/high"
    assert any("monotonic" in i.message.lower() for i in flagged)
