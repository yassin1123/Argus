"""Phase 3 / Week 13 / Day 1 — email exporter tests.

Eight tests per spec covering: subject-line target inclusion, M&A
valuation reference in the recommendation paragraph, growth caveat
referencing the top competitive force, attached-bundle override,
firm-branded signature block, no inline citation markers in the body,
HTML primary-colour application on headings, and a markdown
structure lint.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from core.exports._base import ClaimCitation
from core.exports.email import EmailHtmlExporter, EmailMarkdownExporter


_BRANDING: dict[str, Any] = {
    "primary_color": "#0F6E56",
    "_firm_name": "Argus Demo Boutique",
    "_partner_name": "Jane Bowman",
    "_partner_title": "Partner — Diligence",
}


def _m_and_a_payload() -> dict[str, Any]:
    return {
        "mode": "m_and_a_diligence",
        "recommendation": "PROCEED WITH CONDITIONS",
        "summary": "Stable, diligence-ready.",
        "key_reasons": [
            "Resilient gross margin trajectory through FY21–FY24",
            "Top-3 customer block carries multi-year contracts",
        ],
        "risks": [
            "Concentration risk: top 3 customers account for 47% of revenue",
            "Working-capital seasonality compresses Q1 cash position",
        ],
        "valuation_range": {
            "low":  {"gbp_m": 205.0, "methodology": "DCF @ WACC 10%"},
            "base": {"gbp_m": 220.0, "methodology": "EV/EBITDA 8.5x"},
            "high": {"gbp_m": 235.0, "methodology": "EV/Sales 1.4x"},
        },
        "_engagement_title": "TargetCo M&A diligence",
        "_target_name": "TargetCo Holdings",
        "_firm_name": "Argus Demo Boutique",
    }


def _growth_payload() -> dict[str, Any]:
    return {
        "mode": "growth_strategy",
        "recommendation": "EXPAND INTO UK MID-MARKET",
        "summary": "UK mid-market is the right segment to enter next.",
        "key_reasons": [
            "Adjacent capability set transfers without major hiring",
        ],
        "risks": [
            "Incumbents will respond aggressively on price",
        ],
        "frameworks": {
            "porters_five_forces": {
                "forces": [
                    {"name": "Buyer power", "intensity": "medium"},
                    {"name": "Threat of new entrants", "intensity": "high"},
                    {"name": "Supplier power", "intensity": "low"},
                ]
            }
        },
        "_engagement_title": "UK mid-market entry",
        "_target_name": "Albright & Marsh",
        "_firm_name": "Argus Demo Boutique",
    }


_CITATIONS = [
    ClaimCitation(
        claim_id="claim_1", text="Revenue trajectory",
        source_title="TargetCo CIM", source_type="firm_library",
    ),
    ClaimCitation(
        claim_id="claim_2", text="EBITDA trajectory",
        source_title="10-K 2023", source_type="sec_filing",
    ),
]


# ---------------------------------------------------------------------------
# Test 1 — M&A subject includes target name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_and_a_email_subject_includes_target_name() -> None:
    result = await EmailMarkdownExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    subject = result.metadata["subject"]
    assert "TargetCo Holdings" in subject, f"subject missing target: {subject!r}"
    assert "diligence" in subject.lower(), f"M&A subject lacks 'diligence' marker: {subject!r}"


# ---------------------------------------------------------------------------
# Test 2 — M&A recommendation paragraph references valuation range
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_and_a_email_recommendation_references_valuation() -> None:
    result = await EmailMarkdownExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    body = result.file_bytes.decode("utf-8")
    # Valuation low/base/high should appear, plus the methodology hint.
    assert "205" in body and "235" in body and "220" in body, (
        f"valuation range numbers missing from body: {body!r}"
    )
    assert "EV/EBITDA" in body or "DCF" in body, (
        "valuation methodology missing — recommendation paragraph thin"
    )


# ---------------------------------------------------------------------------
# Test 3 — growth caveat references the top competitive force
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_growth_email_caveat_references_competitive_force() -> None:
    result = await EmailMarkdownExporter().render(
        _growth_payload(), _BRANDING, _CITATIONS,
    )
    body = result.file_bytes.decode("utf-8")
    # The highest-intensity force in the fixture is "Threat of new entrants".
    assert "Critical caveat" in body, "caveat heading missing"
    assert "Threat of new entrants".lower() in body.lower(), (
        f"caveat doesn't reference Porter's top force: {body!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — attached bundle reflects payload override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attached_bundle_lists_available_artifacts() -> None:
    payload = _m_and_a_payload()
    payload["_attached_artifacts"] = [
        {"label": "Custom diligence memo", "detail": "PDF, 30 pages"},
        "1-pager (PDF)",
        {"label": "Deck", "detail": "PPTX, 12 slides"},
    ]
    result = await EmailMarkdownExporter().render(payload, _BRANDING, _CITATIONS)
    body = result.file_bytes.decode("utf-8")
    assert "Custom diligence memo (PDF, 30 pages)" in body
    assert "1-pager (PDF)" in body
    assert "Deck (PPTX, 12 slides)" in body
    # And the default M&A entry that wasn't in the override should NOT appear.
    assert "10 sheets — DCF" not in body, (
        "override leaked the default attachment list"
    )


# ---------------------------------------------------------------------------
# Test 5 — signature block uses firm branding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signature_block_uses_firm_branding() -> None:
    result = await EmailMarkdownExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    body = result.file_bytes.decode("utf-8")
    # The branding-provided partner + title + firm should appear in order.
    sig_zone = body.split("Best regards,", 1)
    assert len(sig_zone) == 2, "missing 'Best regards,' signature anchor"
    sig = sig_zone[1]
    assert "Jane Bowman" in sig, "partner name missing from signature"
    assert "Partner — Diligence" in sig, "partner title missing from signature"
    assert "Argus Demo Boutique" in sig, "firm name missing from signature"


# ---------------------------------------------------------------------------
# Test 6 — no inline citation markers anywhere in the body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_inline_citation_markers_in_body() -> None:
    """The body must never carry [1], <sup>, or [^1] patterns —
    citations live in the attached memo; the email points the reader
    there via the 'Sources' line."""
    result = await EmailMarkdownExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    body = result.file_bytes.decode("utf-8")
    # Check only the body proper — strip the sources/confidentiality footer
    # which legitimately mentions a count.
    head = body.split("---", 1)[0]
    forbidden_patterns = [
        r"\[\d+\]",          # [1], [42] — bracket-number footnote
        r"\[\^\d+\]",        # [^1] — pandoc-style footnote marker
        r"<sup>\d+</sup>",   # HTML superscript chip
    ]
    for pat in forbidden_patterns:
        m = re.search(pat, head)
        assert m is None, f"inline citation marker leaked into body: {m.group(0)!r}"


# ---------------------------------------------------------------------------
# Test 7 — HTML version applies firm primary colour to headings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_html_version_includes_firm_primary_color_in_headings() -> None:
    result = await EmailHtmlExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    html = result.file_bytes.decode("utf-8")
    primary = _BRANDING["primary_color"].upper()
    # Hex appears in inline styles on heading-equivalent elements
    # (markdown-it emits the **bold** sections as <strong>; we colourise
    # those plus h1/h2/h3 with the primary hex).
    assert primary in html.upper(), f"primary colour {primary} not applied: {html[:1200]}"
    # The strong-tag styling should pin the primary colour.
    assert f"color:{primary}".upper() in html.upper() or f"color: {primary}".upper() in html.upper()
    # Subject lives in <title>, body lives in <p>/<strong>; no <img> per hard rule.
    assert "<img" not in html, "email HTML embedded an image — violates hard rule"


# ---------------------------------------------------------------------------
# Test 8 — markdown structure lint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_markdown_version_lints_as_valid_markdown() -> None:
    """Basic structure check — every email must have:
      - a "Dear ...," greeting on the first non-empty line
      - a "**Attached for your review:**" header
      - a numbered list of attachments (1./2./3./...)
      - a "Best regards," signature anchor
      - a horizontal rule before the sources/footer block
      - body word count ≤ 250 (brevity wedge)
      - markdown parses through markdown-it without an exception
    """
    result = await EmailMarkdownExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    body = result.file_bytes.decode("utf-8")

    # 1. Greeting on first non-empty line.
    first_line = next((ln for ln in body.splitlines() if ln.strip()), "")
    assert first_line.startswith("Dear "), f"greeting wrong: {first_line!r}"
    assert first_line.endswith(","), "greeting must end with a comma"

    # 2-4. Required structural anchors.
    assert "**Attached for your review:**" in body
    assert re.search(r"^1\.\s", body, flags=re.MULTILINE), (
        "numbered attachment list missing"
    )
    assert "Best regards," in body

    # 5. Horizontal rule precedes sources/footer.
    assert "\n---\n" in body, "missing --- separator before sources block"

    # 6. Body word count ≤ 250.
    word_count = result.metadata["body_word_count"]
    assert word_count <= 250, f"body too long: {word_count} words (cap 250)"

    # 7. File size cap.
    assert result.file_size < 5_000, f"markdown too large: {result.file_size}B"

    # 8. Parses through markdown-it without error.
    from markdown_it import MarkdownIt
    MarkdownIt("commonmark").parse(body)  # raises on malformed structure
