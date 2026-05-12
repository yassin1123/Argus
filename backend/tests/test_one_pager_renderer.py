"""Phase 3 / Week 10 / Day 3 — 1-pager renderer tests.

Seven tests per spec covering mode dispatch, citation preservation,
branding, and recommendation color-coding. All run as pure unit tests
against ``build_one_pager_context`` + the Jinja templates — no DB,
no FastAPI, no IO.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.exports._base import ClaimCitation
from core.exports.one_pager import OnePagerHtmlExporter
from core.exports.one_pager_renderer import (
    build_one_pager_context,
    classify_recommendation,
    get_recommendation_text,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_BRANDING: dict[str, Any] = {
    "primary_color": "#0F6E56",
    "secondary_color": "#1B1F23",
    "font_family": "Inter, sans-serif",
    "logo_url": "",
    "footer_text": "Boutique Test Firm · Confidential",
}


def _m_and_a_payload() -> dict[str, Any]:
    return {
        "mode": "m_and_a_diligence",
        "recommendation": "PROCEED WITH CONDITIONS",
        "confidence_level": "Medium-High",
        "key_reasons": [
            "Stable cash flow from anchor customers.",
            "Segment leadership in facilities maintenance.",
            "Synergy potential of £6.5m run-rate.",
            "Brand premium attached to historic franchise.",
        ],
        "risks": [
            "Customer concentration in top-3 = 41%.",
            "Halo contract renewal binary in March 2026.",
            "ROI segment EBITDA-negative.",
        ],
        "sources": [
            {"type": "firm_library", "title": "M&A Target Screen Playbook"},
            {"type": "sec_filing", "title": "10-K 2023"},
            {"type": "earnings_transcript", "title": "Q4 2024 call"},
            {"type": "news", "title": "Industry brief"},
        ],
        "valuation_range": {
            "low": {"gbp_m": 205.0, "methodology": "DCF @ WACC 10%"},
            "base": {"gbp_m": 220.0, "methodology": "EV/EBITDA 8.5x"},
            "high": {"gbp_m": 235.0, "methodology": "EV/Sales 1.4x trading comps"},
        },
        "deal_structure_implications": {
            "walk_away_triggers": [
                "If 'Project Halo' contract is not renewed, walk.",
                "If FY25 EBITDA tracks under £18m at H1.",
            ],
        },
        "recommendation_claim_ids": ["claim_1", "claim_2", "claim_3"],
    }


def _growth_payload(with_porters: bool = True) -> dict[str, Any]:
    base: dict[str, Any] = {
        "mode": "growth_strategy",
        "recommendation": "Launch a 9-month Scotland pilot before North-East expansion.",
        "confidence_level": "Medium",
        "key_reasons": [
            "Existing £14.4m revenue base in Scotland.",
            "De-risks Halo renewal exposure with parallel pipeline.",
            "Channel-access model already validated in-region.",
        ],
        "risks": [
            "Halo contract renewal is binary in March 2026.",
            "Capital allocation competes with fleet capex.",
        ],
        "sources": [
            {"type": "firm_library", "title": "Growth Strategy Framework"},
            {"type": "document", "title": "TargetCo Capex"},
        ],
    }
    if with_porters:
        base["frameworks"] = {
            "porters_five_forces": {
                "rivalry": {"intensity": "high"},
                "supplier_power": {"intensity": "moderate"},
                "buyer_power": {"intensity": "high"},
                "substitute_threat": {"intensity": "low"},
                "new_entrant_threat": {"intensity": "moderate"},
            }
        }
    return base


def _citations(n: int) -> list[ClaimCitation]:
    return [
        ClaimCitation(
            claim_id=f"claim_{i+1}",
            text=f"Sample claim text #{i+1} grounded in evidence.",
            source_title=f"Source doc {i+1}",
            source_type="firm_library",
        )
        for i in range(n)
    ]


@pytest.fixture
def exporter() -> OnePagerHtmlExporter:
    return OnePagerHtmlExporter()


# ---------------------------------------------------------------------------
# Test 1 — M&A payload renders with valuation row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renders_m_and_a_with_valuation_row(exporter: OnePagerHtmlExporter) -> None:
    result = await exporter.render(_m_and_a_payload(), _BRANDING, _citations(3))
    html = result.file_bytes.decode("utf-8")
    assert "Valuation range" in html
    # All three valuation points present
    assert "£205" in html
    assert "£220" in html
    assert "£235" in html
    # Walk-away trigger present and references Project Halo
    assert "Walk-away trigger" in html
    assert "Project Halo" in html
    # Mode markers in metadata
    assert result.metadata.get("mode") == "m_and_a_diligence"


# ---------------------------------------------------------------------------
# Test 2 — growth_strategy payload renders with Porter's row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renders_growth_strategy_with_porters_row(
    exporter: OnePagerHtmlExporter,
) -> None:
    result = await exporter.render(_growth_payload(with_porters=True), _BRANDING, _citations(2))
    html = result.file_bytes.decode("utf-8")
    assert "Top competitive force" in html
    # Two forces tied at high — picker takes the first encountered (rivalry).
    assert "rivalry" in html.lower() or "buyer power" in html.lower()
    assert "high" in html.lower()
    # Must NOT include valuation row (M&A-only)
    assert "Valuation range" not in html
    assert result.metadata.get("mode") == "growth_strategy"


# ---------------------------------------------------------------------------
# Test 3 — general mode renders without mode-specific row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renders_general_mode_without_mode_specific_row(
    exporter: OnePagerHtmlExporter,
) -> None:
    payload = {
        "mode": "general",
        "recommendation": "Pursue option A in Q2.",
        "key_reasons": ["Reason 1.", "Reason 2.", "Reason 3."],
        "risks": ["Risk 1.", "Risk 2."],
        "sources": [{"type": "document", "title": "Brief"}],
    }
    result = await exporter.render(payload, _BRANDING, [])
    html = result.file_bytes.decode("utf-8")
    assert "Valuation range" not in html
    assert "Top competitive force" not in html
    # The supplement <div> shouldn't render at all for general mode
    assert "supplement" not in html or html.count('class="supplement"') == 0
    assert result.metadata.get("mode") == "general"


# ---------------------------------------------------------------------------
# Test 4 — citations preserved (data-claim-id markers match input count)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_citations_preserved(exporter: OnePagerHtmlExporter) -> None:
    cits = _citations(5)
    result = await exporter.render(_m_and_a_payload(), _BRANDING, cits)
    html = result.file_bytes.decode("utf-8")
    # Each citation produces one data-claim-id attribute
    n_markers = html.count('data-claim-id="')
    assert n_markers == 5
    # All claim_ids appear in order
    for i in range(1, 6):
        assert f'data-claim-id="claim_{i}"' in html
    # Numbered superscripts present
    for i in range(1, 6):
        assert f"<sup>{i}</sup>" in html
    # Metadata reports the same count
    assert result.claim_citation_count == 5


# ---------------------------------------------------------------------------
# Test 5 — firm branding applied via CSS variables
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_firm_branding_applied(exporter: OnePagerHtmlExporter) -> None:
    branding = {
        "primary_color": "#123456",
        "secondary_color": "#abcdef",
        "font_family": "Georgia, serif",
        "footer_text": "Brand-X Confidential",
        "logo_url": "https://example.com/logo.png",
    }
    result = await exporter.render(_m_and_a_payload(), branding, [])
    html = result.file_bytes.decode("utf-8")
    assert "--primary: #123456" in html
    assert "--secondary: #abcdef" in html
    assert "Georgia, serif" in html
    assert "Brand-X Confidential" in html
    # logo_url rendered as <img src=...> (escaped by Jinja)
    assert "https://example.com/logo.png" in html


# ---------------------------------------------------------------------------
# Test 6 — recommendation color coding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_color_coding(exporter: OnePagerHtmlExporter) -> None:
    """Check the class applied to the recommendation div — the
    base.html.j2 `<style>` block always *defines* rec-green/amber/red
    CSS rules, so checking raw substring would be a false-positive.
    """

    def _applied_class(html: str) -> str:
        import re as _re
        m = _re.search(r'class="recommendation\s+(rec-\w+)"', html)
        assert m, "recommendation div missing rec-* class"
        return m.group(1)

    proceed_payload = {
        "mode": "general",
        "recommendation": "PROCEED",
        "key_reasons": ["r"],
        "risks": ["r"],
        "sources": [],
    }
    assert _applied_class(
        (await exporter.render(proceed_payload, _BRANDING, [])).file_bytes.decode()
    ) == "rec-green"

    pwc_payload = dict(proceed_payload, recommendation="PROCEED WITH CONDITIONS")
    assert _applied_class(
        (await exporter.render(pwc_payload, _BRANDING, [])).file_bytes.decode()
    ) == "rec-amber"

    wa_payload = dict(proceed_payload, recommendation="WALK AWAY — deal kills value.")
    assert _applied_class(
        (await exporter.render(wa_payload, _BRANDING, [])).file_bytes.decode()
    ) == "rec-red"

    rn_payload = dict(proceed_payload, recommendation="RENEGOTIATE on price floor.")
    assert _applied_class(
        (await exporter.render(rn_payload, _BRANDING, [])).file_bytes.decode()
    ) == "rec-red"

    # Pure helper unit checks too
    assert classify_recommendation("PROCEED WITH CONDITIONS") == "amber"
    assert classify_recommendation("proceed") == "green"
    assert classify_recommendation("Walk away — too risky") == "red"
    assert classify_recommendation("Renegotiate the earnout") == "red"


# ---------------------------------------------------------------------------
# Test 7 — non-enum recommendation falls back to neutral
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_recommendation_falls_back_to_neutral(
    exporter: OnePagerHtmlExporter,
) -> None:
    payload = {
        "mode": "growth_strategy",
        "recommendation": "Launch a 9-month Scotland pilot before North-East expansion.",
        "key_reasons": ["Reason A.", "Reason B."],
        "risks": ["Risk X."],
        "sources": [],
    }
    result = await exporter.render(payload, _BRANDING, [])
    html = result.file_bytes.decode("utf-8")
    import re as _re
    m = _re.search(r'class="recommendation\s+(rec-\w+)"', html)
    assert m and m.group(1) == "rec-neutral"
    # Recommendation text still appears verbatim
    assert "Scotland pilot" in html

    # Empty / missing recommendation also resolves to neutral
    assert classify_recommendation("") == "neutral"
    assert classify_recommendation("Some descriptive narrative.") == "neutral"


# ---------------------------------------------------------------------------
# Helper sanity: get_recommendation_text fallbacks
# ---------------------------------------------------------------------------


def test_get_recommendation_text_prefers_executive_summary() -> None:
    payload = {
        "recommendation": "Flat field rec.",
        "executive_summary": {"recommendation": "Exec summary rec wins."},
    }
    assert get_recommendation_text(payload) == "Exec summary rec wins."

    # Falls back when executive_summary missing
    assert get_recommendation_text({"recommendation": "Flat only."}) == "Flat only."
    # Falls back to legacy alias
    assert get_recommendation_text({"recommendation_text": "Legacy alias."}) == "Legacy alias."
    # Empty payload → empty string (renderer substitutes a placeholder)
    assert get_recommendation_text({}) == ""


# ---------------------------------------------------------------------------
# Helper sanity: build_one_pager_context dispatch
# ---------------------------------------------------------------------------


def test_context_dispatch_picks_mode_from_hint_first() -> None:
    payload = {
        "mode": "general",
        "recommendation": "x",
        "valuation_range": {"low": {"gbp_m": 1}, "base": {"gbp_m": 2}, "high": {"gbp_m": 3}},
    }
    ctx_hint = build_one_pager_context(
        payload, {}, [], mode_hint="m_and_a_diligence"
    )
    assert ctx_hint["mode"] == "m_and_a_diligence"
    # No hint, payload says general but valuation_range present → heuristic fallback to M&A
    ctx_heur = build_one_pager_context({"valuation_range": payload["valuation_range"]}, {}, [])
    assert ctx_heur["mode"] == "m_and_a_diligence"
