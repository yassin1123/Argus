"""Phase 3 / Week 13 / Day 4 — interview guide PDF + email branding sweep.

Seven tests per spec covering: PDF validity, multi-page section
break, page footer with firm name, priority-badge presence, email
HTML branding (primary colour applied + no <img>), and a refactoring
sanity check confirming both the interview-guide PDF and the email
PDF route through the shared ``_pdf_helpers`` module.

WeasyPrint's native runtime can be missing on Windows dev hosts; the
PDF-touching tests follow the W10/D4 + W13/D2 pattern — detect
runtime availability and fall back to patching the shared
``_pdf_helpers.html_to_pdf`` + ``_pdf_helpers.pdf_page_count``
symbols so the branching logic still gets exercised.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from core.exports import _pdf_helpers
from core.exports._base import ClaimCitation
from core.exports.email import EmailHtmlExporter, EmailPdfExporter
from core.exports.interview_guide import (
    InterviewGuideHtmlExporter,
    InterviewGuidePdfExporter,
)


_BRANDING: dict[str, Any] = {
    "primary_color": "#0F6E56",
    "_firm_name": "Argus Demo Boutique",
    "_partner_name": "Jane Bowman",
    "_partner_title": "Partner",
    "footer_text": "Argus Demo Boutique · Confidential",
}


def _m_and_a_payload() -> dict[str, Any]:
    return {
        "mode": "m_and_a_diligence",
        "recommendation": "PROCEED WITH CONDITIONS",
        "key_reasons": [
            {"text": "Customer concentration is manageable given multi-year contracts",
             "claim_id": "claim_reason_1"},
            {"text": "EBITDA margin trajectory has been resilient through FY21–FY24",
             "claim_id": "claim_reason_2"},
        ],
        "risks": [
            {"text": "Working-capital seasonality compresses Q1 cash position",
             "claim_id": "claim_risk_1"},
        ],
        "synergy_estimate": {
            "revenue_synergies": [{"magnitude_gbp_m": 5.0}],
            "cost_synergies": [{"magnitude_gbp_m": 3.5}],
        },
        "deal_structure_implications": {
            "walk_away_triggers": ["Top customer churn before close"],
        },
        "gap_report": {
            "missing_evidence": [
                "Scotland-specific competitive landscape",
                "Customer concentration calibration vs peers",
            ],
        },
        "valuation_range": {
            "low":  {"gbp_m": 205.0, "methodology": "DCF"},
            "base": {"gbp_m": 220.0, "methodology": "EV/EBITDA 8.5x"},
            "high": {"gbp_m": 235.0, "methodology": "EV/Sales"},
        },
        "_engagement_title": "TargetCo M&A diligence",
        "_target_name": "TargetCo Holdings",
        "_firm_name": "Argus Demo Boutique",
    }


_CITATIONS = [
    ClaimCitation(claim_id="claim_reason_1", text="x", source_title="CIM", source_type="firm_library"),
]


# ---------------------------------------------------------------------------
# WeasyPrint runtime detection
# ---------------------------------------------------------------------------


def _weasyprint_runtime_ok() -> bool:
    try:
        from weasyprint import HTML
        HTML(string="<html><body>x</body></html>").write_pdf()
        return True
    except Exception:
        return False


_WEASYPRINT_OK = _weasyprint_runtime_ok()


def _fake_pdf_bytes(*, pages: int = 1) -> bytes:
    if _WEASYPRINT_OK:
        from weasyprint import HTML
        body = "".join(
            f'<div style="page-break-after: always">page {i+1}</div>'
            for i in range(pages)
        )
        return HTML(string=f"<html><body>{body}</body></html>").write_pdf()
    try:
        import pikepdf  # type: ignore
    except ImportError:
        return b"%PDF-1.7\n%pretend " + str(pages).encode() + b" pages\n%%EOF"
    import io
    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(595, 842))
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Test 1 — interview guide PDF renders (valid PDF header)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interview_guide_pdf_renders() -> None:
    if not _WEASYPRINT_OK:
        fake_pdf = _fake_pdf_bytes(pages=3)
        with mock.patch.object(_pdf_helpers, "html_to_pdf", return_value=fake_pdf), \
             mock.patch.object(_pdf_helpers, "pdf_page_count", return_value=3):
            result = await InterviewGuidePdfExporter().render(
                _m_and_a_payload(), _BRANDING, _CITATIONS,
            )
        assert result.file_bytes[:4] == b"%PDF"
        assert result.metadata["page_count"] == 3
        return

    result = await InterviewGuidePdfExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    assert result.file_bytes[:4] == b"%PDF"
    assert result.file_size > 0
    assert result.metadata.get("mode") == "m_and_a_diligence"


# ---------------------------------------------------------------------------
# Test 2 — multi-page (≥3 pages — one per section minimum)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interview_guide_pdf_multi_page_for_3_sections() -> None:
    if not _WEASYPRINT_OK:
        # Patch the shared helpers so the test exercises the path
        # without WeasyPrint. The spec asks for ≥3 pages — patch the
        # count to confirm the metadata path forwards correctly.
        fake_pdf = _fake_pdf_bytes(pages=4)
        with mock.patch.object(_pdf_helpers, "html_to_pdf", return_value=fake_pdf), \
             mock.patch.object(_pdf_helpers, "pdf_page_count", return_value=4):
            result = await InterviewGuidePdfExporter().render(
                _m_and_a_payload(), _BRANDING, _CITATIONS,
            )
        assert result.metadata["page_count"] >= 3
        return

    result = await InterviewGuidePdfExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    assert result.metadata["page_count"] >= 3, (
        f"expected ≥3 pages from a 3-section guide, got "
        f"{result.metadata['page_count']}"
    )
    # And below the 8-page hard cap.
    assert result.metadata["page_count"] <= 8


# ---------------------------------------------------------------------------
# Test 3 — page footer contains firm name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interview_guide_pdf_page_footer_contains_firm_name() -> None:
    """The @page bottom-left footer carries 'Confidential — <firm>' on
    every page. With WeasyPrint available we read the rendered PDF
    text and assert the firm name appears; without it, we assert the
    shared print CSS string carries the firm token (the contract that
    the footer will render correctly is upstream of WeasyPrint itself).
    """
    if not _WEASYPRINT_OK:
        # Inspect the CSS the helper produces, not the PDF.
        from core.exports._pdf_helpers import page_header_footer_css
        css = page_header_footer_css(
            firm_name="Argus Demo Boutique",
            engagement_title="TargetCo M&A diligence",
        )
        assert "Argus Demo Boutique" in css
        assert "Confidential" in css
        assert "@bottom-left" in css
        assert "counter(page)" in css
        return

    result = await InterviewGuidePdfExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    import fitz  # PyMuPDF
    with fitz.open(stream=result.file_bytes, filetype="pdf") as doc:
        # Every page's text should carry the firm name (header band)
        # AND the page counter (footer band).
        for page in doc:
            text = page.get_text()
            assert "Argus Demo Boutique" in text, (
                f"firm name missing from page {page.number}: {text[:200]!r}"
            )
            assert "Page" in text and "of" in text, (
                f"page counter missing from page {page.number}"
            )


# ---------------------------------------------------------------------------
# Test 4 — priority badges colourised on rendered output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interview_guide_pdf_priority_badges_colored() -> None:
    """Per spec: HIGH = red, MEDIUM = amber, LOW = green. We verify
    badge presence on the HTML render (which feeds the PDF render);
    the colour-class names are stable contracts the PDF CSS keys off."""
    result = await InterviewGuideHtmlExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    html = result.file_bytes.decode("utf-8")
    # Section A's gap-derived questions are all priority=high.
    assert "argus-priority-high" in html, "HIGH badges missing"
    assert "HIGH" in html
    # The priority hex values are pinned in the CSS payload.
    assert "#B91C1C" in html, "HIGH badge red hex missing"
    assert "#B8860B" in html, "MEDIUM badge amber hex missing"
    assert "#0F6E56" in html, "LOW badge green hex (firm-default) missing"
    # Time chips render with ~N min on every priority line.
    assert 'class="argus-time-chip"' in html


# ---------------------------------------------------------------------------
# Test 5 — email HTML applies firm primary colour to headings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_html_branding_applied() -> None:
    result = await EmailHtmlExporter().render(
        _m_and_a_payload(), _BRANDING, _CITATIONS,
    )
    html = result.file_bytes.decode("utf-8")
    primary = _BRANDING["primary_color"].upper()
    assert primary in html.upper(), (
        f"primary colour {primary} not applied in email HTML"
    )
    # H1/H2/H3/strong styling must use the primary colour explicitly.
    assert f"color:{primary}".upper() in html.upper() or \
           f"color: {primary}".upper() in html.upper()


# ---------------------------------------------------------------------------
# Test 6 — email HTML never embeds the firm logo image
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_html_no_embedded_logo_image() -> None:
    """Hard rule: don't embed the firm logo image in the email HTML.
    Mail clients render <img> inconsistently. Firm name lives in the
    signature as text only."""
    branding_with_logo = dict(_BRANDING)
    branding_with_logo["logo_url"] = "https://example.com/logo.png"

    result = await EmailHtmlExporter().render(
        _m_and_a_payload(), branding_with_logo, _CITATIONS,
    )
    html = result.file_bytes.decode("utf-8")
    assert "<img" not in html, (
        "email HTML embedded an <img> tag — violates hard rule"
    )
    # Logo URL must not leak as a background-image either.
    assert "example.com/logo.png" not in html
    # The firm name MUST appear (it's the text-only branding fallback).
    assert _BRANDING["_firm_name"] in html


# ---------------------------------------------------------------------------
# Test 7 — shared PDF helpers used by BOTH the interview-guide PDF and email PDF
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_page_break_helper_used_in_both_artifacts() -> None:
    """Refactoring sanity check. The shared module exposes
    ``page_break_css`` + ``html_to_pdf`` + ``pdf_page_count``; both
    the interview-guide PDF exporter and the email PDF exporter
    route through it. We verify:

      1. The shared ``page_break_css`` produces the documented CSS
         signature.
      2. Patching ``_pdf_helpers.html_to_pdf`` deflects BOTH the
         interview-guide PDF and the email PDF render paths to the
         fake — proving both exporters share the same WeasyPrint
         integration point.
    """
    # 1. CSS signature.
    css = _pdf_helpers.page_break_css()
    assert "page-break-before: always" in css
    assert "break-before: page" in css
    assert "argus-pdf-section-break" in css

    # 2. Both exporter paths route through the shared html_to_pdf.
    # Single-page fake so the email exporter doesn't trip its overflow
    # gate; interview_guide tolerates any page count ≤ 8.
    fake_pdf = _fake_pdf_bytes(pages=1)
    calls: list[str] = []

    def _spy(html: str, extra_css: list[str] | None = None) -> bytes:
        calls.append("call")
        return fake_pdf

    with mock.patch.object(_pdf_helpers, "html_to_pdf", side_effect=_spy), \
         mock.patch.object(_pdf_helpers, "pdf_page_count", return_value=1):
        ig = await InterviewGuidePdfExporter().render(
            _m_and_a_payload(), _BRANDING, _CITATIONS,
        )
        em = await EmailPdfExporter().render(
            _m_and_a_payload(), _BRANDING, _CITATIONS,
        )
    assert len(calls) == 2, (
        f"expected both PDF exporters to hit shared html_to_pdf once each, "
        f"got {len(calls)} call(s)"
    )
    assert ig.file_bytes == fake_pdf
    # Email PDF wraps the bytes but the underlying call still hit the spy.
    assert em.file_bytes == fake_pdf
