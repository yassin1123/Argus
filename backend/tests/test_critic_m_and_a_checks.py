"""Phase 2 / Week 7 / Day 3 — M&A-specific post-writer critic checks.

Hermetic — pure Python on dict-shaped payloads. Each test exercises
exactly one check.
"""

from __future__ import annotations

from agents.critic_checks import apply_mode_checks
from agents.critic_checks._m_and_a import check_m_and_a


def _ok_valuation():
    return {
        "low": {"gbp_m": 100, "methodology": "DCF @ WACC 12%"},
        "base": {"gbp_m": 130, "methodology": "EV/EBITDA 9.5x precedents"},
        "high": {"gbp_m": 160, "methodology": "EV/Sales 1.3x trading comps"},
    }


def _ok_payload():
    """Minimal-but-clean payload that should produce zero issues."""
    return {
        "valuation_range": _ok_valuation(),
        "synergy_estimate": {
            "dis_synergies": [
                {"type": "Customer attrition", "magnitude_gbp_m": 2.0,
                 "timing_months": 9, "confidence": "medium",
                 "basis_citations": ["WTP study"]},
            ],
        },
        "integration_plan": {
            "first_100_days": [{"workstream": "IT", "owner_role": "CTO"}],
            "first_year": [{"workstream": "Brand", "owner_role": "CMO"}],
        },
        "deal_structure_implications": {
            "walk_away_triggers": [
                "If top 3 customers > 45% of revenue at close, walk.",
            ],
        },
    }


# ---------------------------------------------------------------------------
# 1. test_critic_flags_non_monotonic_valuation
# ---------------------------------------------------------------------------


def test_critic_flags_non_monotonic_valuation() -> None:
    p = _ok_payload()
    p["valuation_range"]["low"]["gbp_m"] = 200  # low > base
    issues = check_m_and_a(p)
    fields = [i.field for i in issues]
    assert "valuation_range" in fields
    msg = next(i.message for i in issues if i.field == "valuation_range")
    assert "monotonic" in msg.lower()


# ---------------------------------------------------------------------------
# 2. test_critic_flags_identical_methodology_across_low_base_high
# ---------------------------------------------------------------------------


def test_critic_flags_identical_methodology_across_low_base_high() -> None:
    p = _ok_payload()
    p["valuation_range"]["low"]["methodology"] = "DCF"
    p["valuation_range"]["base"]["methodology"] = "DCF"
    p["valuation_range"]["high"]["methodology"] = "DCF"
    issues = check_m_and_a(p)
    fields = [i.field for i in issues]
    assert "valuation_range.methodology" in fields


# ---------------------------------------------------------------------------
# 3. test_critic_flags_empty_dis_synergies
# ---------------------------------------------------------------------------


def test_critic_flags_empty_dis_synergies() -> None:
    p = _ok_payload()
    p["synergy_estimate"]["dis_synergies"] = []
    issues = check_m_and_a(p)
    fields = [i.field for i in issues]
    assert "synergy_estimate.dis_synergies" in fields


# ---------------------------------------------------------------------------
# 4. test_critic_flags_walk_away_trigger_without_quantitative_threshold
# ---------------------------------------------------------------------------


def test_critic_flags_walk_away_trigger_without_quantitative_threshold() -> None:
    p = _ok_payload()
    # First trigger has a digit (passes); second is purely categorical (fails).
    p["deal_structure_implications"]["walk_away_triggers"] = [
        "If top 3 customers > 45% at close, walk.",
        "If customer concentration risk materialises.",
    ]
    issues = check_m_and_a(p)
    flagged = [
        i for i in issues
        if i.field.startswith("deal_structure_implications.walk_away_triggers")
    ]
    assert len(flagged) == 1
    assert flagged[0].field == "deal_structure_implications.walk_away_triggers.1"

    # Also confirm a fully-quantitative payload emits zero trigger issues.
    p2 = _ok_payload()
    p2["deal_structure_implications"]["walk_away_triggers"] = [
        "If top 3 customers > 45% at close, walk.",
        "If churn exceeds 8% in month 6, renegotiate.",
    ]
    issues2 = check_m_and_a(p2)
    trigger_issues = [
        i for i in issues2
        if i.field.startswith("deal_structure_implications.walk_away_triggers")
    ]
    assert trigger_issues == []


# ---------------------------------------------------------------------------
# Bonus: registry dispatch sanity
# ---------------------------------------------------------------------------


def test_apply_mode_checks_dispatches_to_general_for_unknown_modes() -> None:
    p = _ok_payload()
    # General-mode runs check_general which is a no-op today.
    assert apply_mode_checks("general", p) == []
    assert apply_mode_checks("does_not_exist", p) == []
    # M&A-mode runs check_m_and_a — same payload, expect zero issues
    # since _ok_payload is intentionally clean.
    assert apply_mode_checks("m_and_a_diligence", p) == []
