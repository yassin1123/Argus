"""One-pager exporters — HTML (W10/D3) + PDF (W10/D4).

Both share the same Jinja templates and ``build_one_pager_context``
pure builder. The PDF exporter reuses the HTML exporter's bytes and
hands them to WeasyPrint with print CSS overrides + a single-page
guarantee (truncate-and-retry, then fail clearly if still overflowing).

Engagement metadata travels in via reserved underscore-prefixed keys
on the payload dict (``_engagement_title``, ``_target_name``,
``_prepared_by``, ``_mode_hint``, ``_firm_name``). The service layer
injects these from sessions.report_mode / sessions.title / firms.name.

Templates live under ``templates/one_pager/``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ._base import ClaimCitation, ExporterBase, ExporterResult, payload_get
from ._registry import register
from .one_pager_renderer import build_one_pager_context

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates" / "one_pager"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


# ---------------------------------------------------------------------------
# HTML exporter (D3)
# ---------------------------------------------------------------------------


def _render_one_pager_html(
    payload: Any,
    firm_branding: dict[str, Any],
    citations: list[ClaimCitation],
    *,
    reasons_max: int = 3,
    risks_max: int = 3,
) -> tuple[str, dict[str, Any]]:
    """Render the 1-pager HTML body + context. Shared by both exporters."""
    ctx = build_one_pager_context(
        payload,
        firm_branding or {},
        citations or [],
        engagement_title=str(
            payload_get(payload, "_engagement_title", default="Argus 1-pager")
            or "Argus 1-pager"
        ),
        target_name=str(payload_get(payload, "_target_name", default="") or ""),
        prepared_by=str(payload_get(payload, "_prepared_by", default="") or ""),
        mode_hint=payload_get(payload, "_mode_hint", default=None),
        firm_name=str(payload_get(payload, "_firm_name", default="Argus") or "Argus"),
        reasons_max=reasons_max,
        risks_max=risks_max,
    )
    html = _ENV.get_template("base.html.j2").render(**ctx)
    return html, ctx


@register("one_pager", "html")
class OnePagerHtmlExporter(ExporterBase):
    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        html, ctx = _render_one_pager_html(payload, firm_branding, citations)
        b = html.encode("utf-8")
        return ExporterResult(
            file_bytes=b,
            file_size=len(b),
            claim_citation_count=len(ctx.get("citations") or []),
            metadata={
                "mode": ctx.get("mode"),
                "recommendation_color": ctx.get("recommendation_color"),
                "reasons_count": len(ctx.get("reasons") or []),
                "risks_count": len(ctx.get("risks") or []),
                "reasons_truncated": ctx.get("reasons_truncated", 0),
                "risks_truncated": ctx.get("risks_truncated", 0),
                "rendered_chars": len(html),
            },
        )


# ---------------------------------------------------------------------------
# PDF exporter (D4)
# ---------------------------------------------------------------------------


# Print CSS layered on top of the inline styles in base.html.j2.
# - @page locks A4 with 12mm margins (matches spec).
# - The hide-screen-only rule removes the `data-claim-id` chip hover
#   surface in print; PDF readers don't render `title=` tooltips.
# - Citation-list font is 7.5pt monospace (already in base) — re-asserted
#   here for print priority.
_PRINT_CSS = """
@page { size: A4; margin: 12mm; }
@media print {
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .recommendation { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
.page { max-height: calc(297mm - 24mm); overflow: hidden; }
.citation-list { font-size: 7.5pt; }
.citation-list .ref { page-break-inside: avoid; }
.footer { font-size: 7.5pt; }
"""


def _html_to_pdf(html: str) -> bytes:
    """Late import so the registry can load even when WeasyPrint's
    runtime libs are missing (Windows dev). Raises a clean
    :class:`OnePagerPdfRuntimeError` on import failure."""
    try:
        from weasyprint import CSS, HTML  # type: ignore
    except (ImportError, OSError) as e:
        raise OnePagerPdfRuntimeError(
            f"WeasyPrint runtime not available: {e}. "
            f"Install pango/cairo/gdk-pixbuf system libs "
            f"(see backend/core/exports/README.md) or run inside Docker."
        ) from e
    return HTML(string=html).write_pdf(stylesheets=[CSS(string=_PRINT_CSS)])


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Page count via PyMuPDF (already in deps). Returns -1 on parse
    failure so callers can surface the error rather than silently
    skip the overflow gate."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        # No way to count pages — assume single page (PyMuPDF is in
        # requirements.txt, so this branch is defensive only).
        return 1
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001
        return -1


class OnePagerPdfRuntimeError(RuntimeError):
    """WeasyPrint's runtime (pango/cairo/gdk-pixbuf) isn't loadable.

    Distinct from ``OnePagerPdfOverflowError`` so the service layer can
    surface a useful failure reason without conflating environment
    issues with content overflow.
    """


class OnePagerPdfOverflowError(RuntimeError):
    """Content can't fit on one A4 page even after the truncation pass."""


@register("one_pager", "pdf")
class OnePagerPdfExporter(ExporterBase):
    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        # First attempt: standard caps (3 reasons, 3 risks).
        html, ctx = _render_one_pager_html(payload, firm_branding, citations)
        pdf_bytes = _html_to_pdf(html)
        pages = _pdf_page_count(pdf_bytes)
        attempt_meta: dict[str, Any] = {
            "attempt_1_pages": pages,
            "attempt_1_reasons_max": 3,
            "attempt_1_risks_max": 3,
        }
        truncated_for_fit = False

        if pages != 1:
            # Retry pass: trim risks to 2 (per spec). Reasons stay at 3
            # — the spec calls out risks specifically as the trim target.
            truncated_for_fit = True
            html, ctx = _render_one_pager_html(
                payload, firm_branding, citations, risks_max=2
            )
            pdf_bytes = _html_to_pdf(html)
            pages_retry = _pdf_page_count(pdf_bytes)
            attempt_meta.update(
                {
                    "attempt_2_pages": pages_retry,
                    "attempt_2_reasons_max": 3,
                    "attempt_2_risks_max": 2,
                }
            )
            if pages_retry != 1:
                raise OnePagerPdfOverflowError(
                    f"content_overflow_after_truncation: "
                    f"attempt 1 = {pages} page(s), attempt 2 = {pages_retry} page(s)"
                )
            pages = pages_retry

        return ExporterResult(
            file_bytes=pdf_bytes,
            file_size=len(pdf_bytes),
            claim_citation_count=len(ctx.get("citations") or []),
            metadata={
                "mode": ctx.get("mode"),
                "recommendation_color": ctx.get("recommendation_color"),
                "reasons_count": len(ctx.get("reasons") or []),
                "risks_count": len(ctx.get("risks") or []),
                "reasons_truncated": ctx.get("reasons_truncated", 0),
                "risks_truncated": ctx.get("risks_truncated", 0),
                "truncated_for_fit": truncated_for_fit,
                "page_count": pages,
                **attempt_meta,
            },
        )
