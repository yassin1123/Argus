"""Phase 3 / Week 13 / Day 2 — attachment-bundle awareness + PDF tests.

Six tests per spec covering:
  1. Email lists only the artifacts that actually exist (memo + 1-pager).
  2. Email lists all four when the full bundle is generated.
  3. Email flags a stale artifact when the payload_snapshot diverges
     from the current session payload.
  4. Email PDF renders single-page.
  5. Email PDF truncates an overly long body before re-rendering.
  6. With no available artifacts, the email omits the attachment
     section entirely.

WeasyPrint's native runtime can be missing on Windows dev hosts; the
PDF-touching tests mirror the W10/D4 one_pager_pdf test pattern —
detect runtime availability, fall back to mocking ``_html_to_pdf``
and ``_pdf_page_count`` so the branching logic still gets exercised.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock

import pytest

from core.exports import email as email_module
from core.exports._base import ClaimCitation
from core.exports.email import (
    EmailMarkdownExporter,
    EmailPdfExporter,
)
from core.exports.email_builder import EmailBuilder


_BRANDING: dict[str, Any] = {
    "primary_color": "#0F6E56",
    "_firm_name": "Argus Demo Boutique",
    "_partner_name": "Jane Bowman",
    "_partner_title": "Partner",
}


def _payload(*, n_reasons: int = 2, n_risks: int = 2) -> dict[str, Any]:
    return {
        "mode": "m_and_a_diligence",
        "recommendation": "PROCEED WITH CONDITIONS",
        "summary": "Stable diligence target.",
        "key_reasons": [
            f"Reason {i+1} drives the case." for i in range(n_reasons)
        ],
        "risks": [
            f"Risk {i+1} could change the outcome." for i in range(n_risks)
        ],
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
    ClaimCitation(claim_id="claim_1", text="x", source_title="CIM", source_type="firm_library"),
]


# ---------------------------------------------------------------------------
# Test 1 — email lists only the artifacts that actually exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_lists_only_available_artifacts() -> None:
    """Session has a memo + 1-pager but no deck/Excel — email mentions
    only those two."""
    available = [
        {"artifact_type": "memo", "format": "pdf", "metadata": {"page_count": 24}},
        {"artifact_type": "one_pager", "format": "pdf", "metadata": {"page_count": 1}},
    ]
    payload = _payload()
    payload["_available_artifacts"] = available

    result = await EmailMarkdownExporter().render(payload, _BRANDING, _CITATIONS)
    body = result.file_bytes.decode("utf-8")

    # The bundle bullets exist.
    assert "**Attached for your review:**" in body
    # Memo + 1-pager are present.
    assert "Diligence memo" in body
    assert "Executive 1-pager" in body
    # Deck + Financial model are absent (not in the available list).
    assert "Deck (PPTX" not in body, f"deck leaked into bundle: {body!r}"
    assert "Financial model" not in body, f"excel leaked into bundle: {body!r}"


# ---------------------------------------------------------------------------
# Test 2 — full bundle lists all four
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_lists_all_four_when_all_exist() -> None:
    """Session has the full memo + 1-pager + deck + excel_model set —
    email mentions all four in the logical order regardless of the
    order they appear in the available_artifacts list."""
    available = [
        # Deliberately scrambled order — builder should still emit
        # memo → 1-pager → deck → excel_model.
        {"artifact_type": "excel_model", "format": "xlsx", "metadata": {"sheet_count": 10}},
        {"artifact_type": "deck", "format": "pptx", "metadata": {"slide_count": 11}},
        {"artifact_type": "memo", "format": "pdf", "metadata": {"page_count": 24}},
        {"artifact_type": "one_pager", "format": "html", "metadata": {}},
    ]
    payload = _payload()
    payload["_available_artifacts"] = available

    result = await EmailMarkdownExporter().render(payload, _BRANDING, _CITATIONS)
    body = result.file_bytes.decode("utf-8")

    # Each artifact is mentioned exactly once.
    assert body.count("Diligence memo") == 1
    assert body.count("Executive 1-pager") == 1
    assert body.count("Deck (") == 1
    assert body.count("Financial model") == 1

    # Logical ordering — memo first, excel_model last.
    pos_memo = body.find("Diligence memo")
    pos_op = body.find("Executive 1-pager")
    pos_deck = body.find("Deck (")
    pos_excel = body.find("Financial model")
    assert pos_memo < pos_op < pos_deck < pos_excel, (
        f"bundle ordering wrong: memo={pos_memo} op={pos_op} "
        f"deck={pos_deck} excel={pos_excel}"
    )

    # Detail strings from metadata propagate.
    assert "24 pages" in body
    assert "11 slides" in body
    assert "10 sheets" in body


# ---------------------------------------------------------------------------
# Test 3 — stale artifact flagged in the email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_flags_stale_artifact() -> None:
    """When an artifact's frozen payload_snapshot diverges from the
    current payload, the email annotates the line with 'may need refresh'."""
    available = [
        {
            "artifact_type": "memo",
            "format": "pdf",
            "metadata": {"page_count": 24},
            "is_stale": True,
            "generated_at": datetime.now(tz=timezone.utc) - timedelta(days=3),
        },
        {
            "artifact_type": "one_pager",
            "format": "pdf",
            "metadata": {"page_count": 1},
            "is_stale": False,
        },
    ]
    payload = _payload()
    payload["_available_artifacts"] = available

    result = await EmailMarkdownExporter().render(payload, _BRANDING, _CITATIONS)
    body = result.file_bytes.decode("utf-8")

    # Memo line carries the annotation.
    assert "may need refresh" in body, f"stale flag missing: {body!r}"
    # 1-pager line does NOT carry the annotation (only the memo is stale).
    op_line = next(ln for ln in body.splitlines() if "Executive 1-pager" in ln)
    assert "may need refresh" not in op_line, (
        f"non-stale 1-pager incorrectly flagged: {op_line!r}"
    )
    # The relative-age phrase fires.
    assert "generated 3 days ago" in body


# ---------------------------------------------------------------------------
# Test 4 — email PDF is single-page
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
        # Hand-rolled marker bytes — page count must be patched.
        return b"%PDF-1.7\n%pretend " + str(pages).encode() + b" pages\n%%EOF"
    import io

    pdf = pikepdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(595, 842))
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_email_pdf_is_single_page() -> None:
    available = [
        {"artifact_type": "memo", "format": "pdf", "metadata": {"page_count": 24}},
        {"artifact_type": "one_pager", "format": "pdf", "metadata": {"page_count": 1}},
        {"artifact_type": "deck", "format": "pptx", "metadata": {"slide_count": 11}},
        {"artifact_type": "excel_model", "format": "xlsx", "metadata": {"sheet_count": 10}},
    ]
    payload = _payload()
    payload["_available_artifacts"] = available

    if not _WEASYPRINT_OK:
        fake_pdf = _fake_pdf_bytes(pages=1)
        with mock.patch.object(email_module, "_html_to_pdf", return_value=fake_pdf), \
             mock.patch.object(email_module, "_pdf_page_count", return_value=1):
            result = await EmailPdfExporter().render(payload, _BRANDING, _CITATIONS)
        assert result.metadata["page_count"] == 1
        assert result.metadata["truncated_for_fit"] is False
        return

    result = await EmailPdfExporter().render(payload, _BRANDING, _CITATIONS)
    assert result.file_bytes[:4] == b"%PDF"
    assert result.metadata["page_count"] == 1
    assert result.metadata["truncated_for_fit"] is False
    assert result.metadata["mode"] == "m_and_a_diligence"


# ---------------------------------------------------------------------------
# Test 5 — long body triggers truncation, still single page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_pdf_truncates_long_body() -> None:
    """Synthesize a payload with absurdly long key_reasons/risks so the
    rendered email pushes onto page 2 on attempt 1. After truncation,
    the PDF should fit one page and the metadata flags
    ``truncated_for_fit``."""
    payload = _payload(n_reasons=5, n_risks=5)
    # Inflate reason + risk text to push the body over the page break.
    payload["key_reasons"] = [
        "Resilient gross margin trajectory through FY21–FY24 underpinned by "
        "a multi-year contract base and durable pricing power across the "
        "automotive aftermarket segment, supported by structurally low "
        "customer churn (<3% on the top-50 cohort), recurring service "
        "revenue mix expansion, and a defensible position in the dealer "
        "network that competitors have not been able to displace despite "
        "repeated price-led entry attempts over the prior eighteen months. " * 3
        for _ in range(5)
    ]
    payload["risks"] = [
        "Concentration risk: top-three customer block accounts for 47% of "
        "revenue and renegotiates contract pricing on a rolling 24-month "
        "cadence — combined with the working-capital seasonality that "
        "compresses Q1 cash position by 18-22% year-over-year, this means "
        "any single counterparty walking would materially impair the "
        "valuation case, and our diligence has surfaced two distinct "
        "operational dependencies on that block that we'd want quantified "
        "before close. " * 3
        for _ in range(5)
    ]
    payload["_available_artifacts"] = [
        {"artifact_type": "memo", "format": "pdf", "metadata": {"page_count": 60}},
    ]

    # Force the page-count gate to fire — attempt 1 sees 2 pages, attempt 2
    # sees 1 page. We patch _pdf_page_count to return that sequence so the
    # test exercises the truncation branch deterministically, independent of
    # what WeasyPrint thinks of the body length on this host.
    page_seq = iter([2, 1])
    fake_pdf = _fake_pdf_bytes(pages=1)

    with mock.patch.object(email_module, "_html_to_pdf", return_value=fake_pdf), \
         mock.patch.object(email_module, "_pdf_page_count", side_effect=lambda b: next(page_seq)):
        result = await EmailPdfExporter().render(payload, _BRANDING, _CITATIONS)

    assert result.metadata["truncated_for_fit"] is True, (
        "truncated_for_fit flag should fire when attempt 1 produces 2 pages"
    )
    assert result.metadata["page_count"] == 1
    assert result.metadata["attempt_1_pages"] == 2
    assert result.metadata["attempt_2_pages"] == 1


# ---------------------------------------------------------------------------
# Test 6 — no available artifacts → no attachment section
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_available_artifacts_email_omits_attachment_section() -> None:
    """When the service layer reports zero ready artifacts for the
    session, the email omits the 'Attached for your review' block
    entirely — the consultant fires the email before generating the
    bundle (unusual but legitimate flow)."""
    payload = _payload()
    # Pass an explicit empty list (not None) — signals "service truth:
    # nothing ready yet". The W13/D1 default-bundle fallback is
    # disabled in that case.
    payload["_available_artifacts"] = []

    result = await EmailMarkdownExporter().render(payload, _BRANDING, _CITATIONS)
    body = result.file_bytes.decode("utf-8")

    assert "**Attached for your review:**" not in body, (
        f"attachment section should be omitted when no artifacts exist: {body!r}"
    )
    # The numbered list anchors should also be gone.
    import re as _re
    assert _re.search(r"^1\.\s", body, flags=_re.MULTILINE) is None, (
        "numbered list shouldn't render when there are no attachments"
    )
    # Body still has the lede + recommendation + caveat + signature.
    assert "Dear [Client name]" in body
    assert "Best regards," in body


# ---------------------------------------------------------------------------
# Bonus — direct EmailBuilder API parity (kwarg path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_builder_kwarg_path_matches_payload_key() -> None:
    """The W13/D2 EmailBuilder accepts ``available_artifacts`` as a
    constructor kwarg AND a ``_available_artifacts`` payload key.
    Both paths should render identical output (sanity check that
    the service-layer integration path doesn't drift from the
    direct-API path tests rely on)."""
    available = [
        {"artifact_type": "memo", "format": "pdf", "metadata": {"page_count": 24}},
        {"artifact_type": "deck", "format": "pptx", "metadata": {"slide_count": 11}},
    ]
    md_via_kwarg = EmailBuilder(
        _payload(), _BRANDING, _CITATIONS, available_artifacts=available
    ).build_markdown()
    payload_with_key = _payload()
    payload_with_key["_available_artifacts"] = available
    md_via_payload = EmailBuilder(
        payload_with_key, _BRANDING, _CITATIONS,
    ).build_markdown()
    assert md_via_kwarg == md_via_payload
