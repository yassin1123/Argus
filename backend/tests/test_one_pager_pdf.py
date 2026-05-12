"""Phase 3 / Week 10 / Day 4 — 1-pager PDF exporter tests.

Five tests per spec. WeasyPrint's runtime needs system libs
(pango/cairo/gdk-pixbuf) that may not be available on every dev
host — so each test that exercises a real WeasyPrint call is
gated behind a ``pytest.importorskip``-style probe, and a small,
deterministic fake-PDF substitute is used to assert the
exporter's control flow (single-page guarantee, truncation
retry, runtime-error path).

Test 1 — test_renders_pdf_from_html
Test 2 — test_pdf_is_single_page
Test 3 — test_citations_converted_to_footnotes
Test 4 — test_overflow_triggers_truncation
Test 5 — test_overflow_after_truncation_fails_cleanly
"""

from __future__ import annotations

import re
from typing import Any
from unittest import mock

import pytest

from core.exports._base import ClaimCitation
from core.exports import one_pager as op_module
from core.exports.one_pager import (
    OnePagerPdfExporter,
    OnePagerPdfOverflowError,
)


# ---------------------------------------------------------------------------
# Helpers — detect whether WeasyPrint's native runtime works on this host.
# When it doesn't (e.g. Windows without GTK), we use a tiny fake that
# exercises the exporter's branching without crossing the C-lib boundary.
# ---------------------------------------------------------------------------


def _weasyprint_runtime_ok() -> bool:
    try:
        from weasyprint import HTML  # noqa: F401
        # Trigger one real render so OSError surfaces here, not in the test.
        HTML(string="<html><body>x</body></html>").write_pdf()
        return True
    except Exception:
        return False


_WEASYPRINT_OK = _weasyprint_runtime_ok()


def _fake_pdf_bytes(*, pages: int = 1) -> bytes:
    """A minimum-viable PDF byte payload PyMuPDF (fitz) can parse.

    Pages are produced via a real WeasyPrint call when available
    (cleanest), else we build a hand-rolled multi-page PDF stub.
    """
    if _WEASYPRINT_OK:
        from weasyprint import HTML
        body = "".join(
            f'<div style="page-break-after: always">page {i+1}</div>'
            for i in range(pages)
        )
        return HTML(string=f"<html><body>{body}</body></html>").write_pdf()
    # Hand-rolled fallback: build a minimal valid PDF with N empty pages.
    # PyMuPDF accepts this shape.
    import pikepdf  # type: ignore

    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(595, 842))  # A4
    import io
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _try_fake_pdf(pages: int) -> bytes:
    """Helper that tries the WeasyPrint path; if unavailable AND
    pikepdf is unavailable too, builds a marker bytestring so tests
    that don't inspect pages can still proceed (we'll monkey-patch
    page counting in those cases)."""
    try:
        return _fake_pdf_bytes(pages=pages)
    except Exception:
        # Smallest substitute that callers can identify.
        return b"%PDF-1.7\n%pretend " + str(pages).encode() + b" pages\n%%EOF"


# ---------------------------------------------------------------------------
# Sample fixtures
# ---------------------------------------------------------------------------


def _payload(*, n_risks: int = 3, n_reasons: int = 4) -> dict[str, Any]:
    return {
        "mode": "m_and_a_diligence",
        "recommendation": "PROCEED WITH CONDITIONS",
        "confidence_level": "Medium-High",
        "key_reasons": [f"Reason {i+1} drives the recommendation." for i in range(n_reasons)],
        "risks": [f"Risk {i+1} could change the outcome." for i in range(n_risks)],
        "sources": [
            {"type": "firm_library", "title": "M&A Playbook"},
            {"type": "sec_filing", "title": "10-K 2023"},
        ],
        "valuation_range": {
            "low": {"gbp_m": 205.0}, "base": {"gbp_m": 220.0}, "high": {"gbp_m": 235.0},
        },
        "deal_structure_implications": {
            "walk_away_triggers": ["If Project Halo isn't renewed, walk."],
        },
    }


def _citations(n: int) -> list[ClaimCitation]:
    return [
        ClaimCitation(
            claim_id=f"claim_{i+1}",
            text=f"Claim text #{i+1}",
            source_title=f"Doc {i+1}",
            source_type="firm_library",
        )
        for i in range(n)
    ]


_BRANDING: dict[str, Any] = {
    "primary_color": "#0F6E56",
    "secondary_color": "#1B1F23",
    "font_family": "Inter, sans-serif",
    "footer_text": "Test Firm · Confidential",
}


@pytest.fixture
def exporter() -> OnePagerPdfExporter:
    return OnePagerPdfExporter()


# ---------------------------------------------------------------------------
# Test 1 — PDF render produces a valid PDF byte stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renders_pdf_from_html(exporter: OnePagerPdfExporter) -> None:
    """Smoke: render() returns bytes that start with %PDF and the
    exporter reports the single-page metadata."""
    if not _WEASYPRINT_OK:
        # When the native runtime is missing, bypass WeasyPrint entirely:
        # the exporter still calls _html_to_pdf which we patch with a
        # fake-PDF builder, then page-counts as 1.
        fake_pdf = _try_fake_pdf(1)
        with mock.patch.object(op_module, "_html_to_pdf", return_value=fake_pdf), \
             mock.patch.object(op_module, "_pdf_page_count", return_value=1):
            result = await exporter.render(_payload(), _BRANDING, _citations(3))
        assert result.file_bytes[:4] == b"%PDF"
        assert result.file_size > 0
        assert result.metadata.get("page_count") == 1
        return

    result = await exporter.render(_payload(), _BRANDING, _citations(3))
    assert result.file_bytes[:4] == b"%PDF", f"unexpected header: {result.file_bytes[:8]!r}"
    assert result.file_size > 0
    assert result.metadata.get("page_count") == 1
    assert result.metadata.get("mode") == "m_and_a_diligence"


# ---------------------------------------------------------------------------
# Test 2 — output is single-page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_is_single_page(exporter: OnePagerPdfExporter) -> None:
    if not _WEASYPRINT_OK:
        with mock.patch.object(op_module, "_html_to_pdf", return_value=_try_fake_pdf(1)), \
             mock.patch.object(op_module, "_pdf_page_count", return_value=1):
            result = await exporter.render(_payload(), _BRANDING, _citations(2))
    else:
        result = await exporter.render(_payload(), _BRANDING, _citations(2))
    assert result.metadata["page_count"] == 1
    # Truncation flag stays False on a comfortable-content payload.
    assert result.metadata.get("truncated_for_fit") is False


# ---------------------------------------------------------------------------
# Test 3 — citation markers preserved into the PDF (footnote numbers)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_citations_converted_to_footnotes(exporter: OnePagerPdfExporter) -> None:
    """The HTML has numbered <sup>N</sup> citation markers. In PDF
    form each must survive: we extract the PDF's text and assert each
    of the input claim_ids' marker numbers is present.

    Skips when WeasyPrint's native runtime isn't available — PDF text
    extraction needs a real render.
    """
    if not _WEASYPRINT_OK:
        pytest.skip("WeasyPrint runtime not available on this host")

    cits = _citations(5)
    result = await exporter.render(_payload(), _BRANDING, cits)

    import fitz  # PyMuPDF
    with fitz.open(stream=result.file_bytes, filetype="pdf") as doc:
        text = "".join(p.get_text("text") for p in doc)
    # Each citation gets a numbered superscript + its claim_id appears.
    for i in range(1, 6):
        assert f"claim_{i}" in text, f"citation claim_{i} missing in PDF text"
    # The 5 distinct citation indices appear (1..5)
    digits = [int(m) for m in re.findall(r"\b(\d)\b", text)]
    assert {1, 2, 3, 4, 5}.issubset(set(digits)), f"missing citation indices in {digits}"
    assert result.claim_citation_count == 5


# ---------------------------------------------------------------------------
# Test 4 — overflow triggers the truncation pass (risks 3 → 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overflow_triggers_truncation(exporter: OnePagerPdfExporter) -> None:
    """Simulate first-pass overflow: page_count==2 on attempt 1, then
    page_count==1 on attempt 2. The exporter should rebuild HTML with
    risks_max=2 and succeed. risks_truncated metadata reflects the
    trimmed items."""
    pages_sequence = [2, 1]
    page_counts = iter(pages_sequence)

    def _fake_page_count(_pdf: bytes) -> int:
        return next(page_counts)

    pdf_stub = b"%PDF-1.7\n%stub\n%%EOF"

    with mock.patch.object(op_module, "_html_to_pdf", return_value=pdf_stub), \
         mock.patch.object(op_module, "_pdf_page_count", side_effect=_fake_page_count):
        # 8 risks → first pass keeps 3, retries with 2.
        result = await exporter.render(_payload(n_risks=8), _BRANDING, _citations(3))

    assert result.metadata.get("truncated_for_fit") is True
    assert result.metadata["attempt_1_pages"] == 2
    assert result.metadata["attempt_2_pages"] == 1
    assert result.metadata["attempt_2_risks_max"] == 2
    assert result.metadata["attempt_2_reasons_max"] == 2
    # Final renderer config landed at risks=2; risks_truncated reflects
    # 8 - 2 = 6 trimmed.
    assert result.metadata["risks_count"] == 2
    assert result.metadata["risks_truncated"] == 6


# ---------------------------------------------------------------------------
# Test 5 — overflow that survives truncation fails with clear reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overflow_after_truncation_fails_cleanly(
    exporter: OnePagerPdfExporter,
) -> None:
    """Both passes overflow → OnePagerPdfOverflowError with the
    spec'd ``content_overflow_after_truncation`` substring so the
    service layer surfaces a meaningful failure reason."""
    pdf_stub = b"%PDF-1.7\n%stub\n%%EOF"

    with mock.patch.object(op_module, "_html_to_pdf", return_value=pdf_stub), \
         mock.patch.object(op_module, "_pdf_page_count", return_value=3):
        with pytest.raises(OnePagerPdfOverflowError) as exc:
            await exporter.render(_payload(n_risks=8), _BRANDING, _citations(3))

    assert "content_overflow_after_truncation" in str(exc.value)
    assert "attempt 1 = 3 page(s)" in str(exc.value)
    assert "attempt 2 = 3 page(s)" in str(exc.value)
