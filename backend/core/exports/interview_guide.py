"""Interview guide exporters — markdown (W13/D3) + HTML / PDF (W13/D4).

The interview guide is the consultant's tool for expert validation
calls. Three sections per spec:

  - A: Critical evidence gaps (gap_report-derived, capped at 7).
  - B: Pressure-test the recommendation (top-3 reasons + top-2 risks
       turned into questions, capped at 5).
  - C: Mode-specific deep-dive (M&A integration / growth market
       dynamics / general failure-mode scan, capped at 5).

Total cap across the guide: 15 questions (45-60 min realistic budget).

Reserved underscore-prefixed payload keys consumed by the builder:
  - ``gap_report``: top-level dict {missing_evidence: [...], ...}.
    The service layer injects this via ``_gap_report`` when generating
    interview_guide artifacts so the builder doesn't need a DB round-trip.
  - ``_engagement_title``, ``_target_name``, ``_firm_name``,
    ``_mode_hint``: same as the other exporters.
"""

from __future__ import annotations

import re
from typing import Any

from ._base import ClaimCitation, ExporterBase, ExporterResult, payload_get
from . import _pdf_helpers
from ._pdf_helpers import (
    PAGE_BREAK_CLASS,
    PdfRuntimeError,
    page_break_css,
    page_header_footer_css,
)
from ._registry import register
from .interview_guide_builder import InterviewGuideBuilder

_DEFAULT_PRIMARY_HEX = "#0F6E56"
_DEFAULT_TEXT_HEX = "#1B1F23"
_DEFAULT_MUTED_HEX = "#5B6470"
_DEFAULT_BG_HEX = "#FFFFFF"

# Per-priority badge colours. Per spec: HIGH = red, MEDIUM = amber,
# LOW = green. Background colours are deliberately desaturated so the
# badge reads as a tag, not a banner.
_PRIORITY_BADGE: dict[str, tuple[str, str]] = {
    "high":   ("#B91C1C", "#FEE2E2"),  # text, background
    "medium": ("#B8860B", "#FFF4D6"),
    "low":    ("#0F6E56", "#D7EFE3"),
}


def _normalise_hex(raw: Any, default: str) -> str:
    if isinstance(raw, str):
        s = raw.strip()
        if not s.startswith("#"):
            s = "#" + s.lstrip("#")
        if len(s) == 7 and all(c in "0123456789abcdefABCDEF" for c in s[1:]):
            return s
    return default


def _build_html(
    payload: Any,
    firm_branding: dict[str, Any] | None,
    citations: list[ClaimCitation],
) -> tuple[str, InterviewGuideBuilder]:
    """Shared HTML render used by both the HTML and PDF exporters.

    Builds the markdown via the W13/D3 builder then post-processes it
    into a branded HTML document with priority badges + time-estimate
    chips inline next to each question title. Section A / B / C
    headings receive a ``argus-pdf-section-break`` class so the PDF
    exporter can land each on a fresh page.
    """
    builder = InterviewGuideBuilder(payload, firm_branding, citations)
    md = builder.build_markdown()

    primary = _normalise_hex((firm_branding or {}).get("primary_color"), _DEFAULT_PRIMARY_HEX)
    body_html = _markdown_to_branded_html(md, primary_hex=primary)
    title = f"Interview Guide — {builder.target_name or builder.engagement_title or 'Argus engagement'}"

    full = (
        '<!doctype html>\n<html><head><meta charset="utf-8" />'
        f'<title>{_escape(title)}</title>'
        f'<style>{_inline_screen_css(primary)}</style>'
        "</head>"
        f'<body><main class="argus-interview-guide">{body_html}</main></body></html>'
    )
    return full, builder


def _inline_screen_css(primary_hex: str) -> str:
    """Light-touch screen CSS so the HTML preview reads well in a
    browser tab. The PDF exporter layers additional print CSS on top
    via the shared helpers."""
    return (
        "body{margin:24px auto;max-width:760px;background:#FFFFFF;"
        "font-family:Georgia,serif;color:#1B1F23;line-height:1.5;}"
        f"h1{{color:{primary_hex};font-size:22pt;margin:0 0 8px 0;}}"
        f"h2{{color:{primary_hex};font-size:15pt;margin:24px 0 10px 0;}}"
        f"h3{{color:{primary_hex};font-size:12pt;margin:18px 0 6px 0;}}"
        "ul{margin:0 0 12px 22px;padding:0;}"
        f"strong{{color:{primary_hex};font-weight:600;}}"
        "em{color:#5B6470;font-style:italic;}"
        ".argus-pdf-section-break{margin-top:28px;}"
        ".argus-priority-badge,.argus-time-chip{display:inline-block;"
        "padding:1px 6px;border-radius:3px;font-family:Inter,Arial,sans-serif;"
        "font-size:9pt;font-weight:600;margin-left:6px;letter-spacing:0.02em;}"
        ".argus-time-chip{background:#EEF1F4;color:#5B6470;font-weight:500;}"
        ".argus-priority-high{color:#B91C1C;background:#FEE2E2;}"
        ".argus-priority-medium{color:#B8860B;background:#FFF4D6;}"
        ".argus-priority-low{color:#0F6E56;background:#D7EFE3;}"
        ".argus-section-rule{border:0;border-top:1px solid #E5E7EB;margin:18px 0;}"
    )


_QUESTION_HEADING_RE = re.compile(
    r"^### ([ABC]\d+)\.\s*(.*?)\s*$", flags=re.MULTILINE,
)


def _markdown_to_branded_html(md: str, *, primary_hex: str) -> str:
    """Convert the W13/D3 markdown into branded HTML with priority
    badges + time chips lifted from the markdown bullet list.

    We do the conversion in three passes:
      1. Pre-parse: collect (priority, minutes) per question heading
         from the bullets immediately below the heading.
      2. markdown-it converts the body.
      3. Post-process: inject the badge + chip span into each
         ``<h3>`` that matches the question pattern, tag each
         Section-N heading with the page-break class, and apply
         primary-colour inline styles where useful.
    """
    from markdown_it import MarkdownIt

    # ── Pass 1: gather metadata per anchor ──────────────────────────
    metadata_by_anchor: dict[str, dict[str, str]] = {}
    blocks = md.split("\n### ")
    for block in blocks:
        m = re.match(r"([ABC]\d+)\.\s*(.*?)\n", block, flags=re.DOTALL)
        if not m:
            continue
        anchor = m.group(1)
        # Find Priority + Time bullets in the block tail.
        prio_match = re.search(r"\*\*Priority:\*\*\s*([A-Z]+)", block)
        time_match = re.search(r"\*\*Time:\*\*\s*~?(\d+)\s*min", block)
        metadata_by_anchor[anchor] = {
            "priority": (prio_match.group(1).lower() if prio_match else "medium"),
            "minutes": (time_match.group(1) if time_match else ""),
        }

    # ── Pass 2: markdown → HTML. ────────────────────────────────────
    mdit = MarkdownIt("commonmark", {"breaks": False, "linkify": False})
    html = mdit.render(md)

    # ── Pass 3: post-process ────────────────────────────────────────
    # 3a. Tag Section A/B/C h2s with the page-break class.
    html = re.sub(
        r"<h2>(Section [ABC] —)",
        rf'<h2 class="{PAGE_BREAK_CLASS}">\1',
        html,
    )

    # 3b. Inject priority badges + time chips into each <h3>A1./B1./...
    def _h3_inject(m: re.Match[str]) -> str:
        anchor = m.group(1)
        rest = m.group(2)
        meta = metadata_by_anchor.get(anchor, {})
        prio = (meta.get("priority") or "medium").lower()
        minutes = meta.get("minutes") or ""
        badge = (
            f'<span class="argus-priority-badge argus-priority-{prio}">'
            f"{prio.upper()}</span>"
        )
        chip = ""
        if minutes:
            chip = f'<span class="argus-time-chip">~{minutes} min</span>'
        return f"<h3>{anchor}. {rest}{badge}{chip}</h3>"

    html = re.sub(
        r"<h3>([ABC]\d+)\.\s*(.*?)</h3>", _h3_inject, html, flags=re.DOTALL,
    )

    # 3c. Replace <hr> with the screen-safe variant we styled above.
    html = re.sub(r"<hr\s*/?>", '<hr class="argus-section-rule" />', html)

    return html


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# Markdown exporter (W13/D3) — kept above so the registry order matches the
# day-by-day shipping history.
# ---------------------------------------------------------------------------


@register("interview_guide", "md")
class InterviewGuideMarkdownExporter(ExporterBase):
    artifact_type = "interview_guide"
    format = "md"

    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        builder = InterviewGuideBuilder(payload, firm_branding, citations)
        md = builder.build_markdown()
        encoded = md.encode("utf-8")
        return ExporterResult(
            file_bytes=encoded,
            file_size=len(encoded),
            claim_citation_count=builder.citation_count,
            metadata={
                "format_subtype": "markdown",
                "mode": builder.mode,
                "question_count": builder.question_count,
                "section_a_count": len(builder.section_a),
                "section_b_count": len(builder.section_b),
                "section_c_count": len(builder.section_c),
                "cited_claim_ids": list(builder.cited_claim_ids),
            },
        )


# ---------------------------------------------------------------------------
# HTML exporter (W13/D4)
# ---------------------------------------------------------------------------


@register("interview_guide", "html")
class InterviewGuideHtmlExporter(ExporterBase):
    artifact_type = "interview_guide"
    format = "html"

    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        html, builder = _build_html(payload, firm_branding, citations)
        encoded = html.encode("utf-8")
        return ExporterResult(
            file_bytes=encoded,
            file_size=len(encoded),
            claim_citation_count=builder.citation_count,
            metadata={
                "format_subtype": "html",
                "mode": builder.mode,
                "question_count": builder.question_count,
                "section_a_count": len(builder.section_a),
                "section_b_count": len(builder.section_b),
                "section_c_count": len(builder.section_c),
                "cited_claim_ids": list(builder.cited_claim_ids),
            },
        )


# ---------------------------------------------------------------------------
# PDF exporter (W13/D4)
# ---------------------------------------------------------------------------


_INTERVIEW_PDF_HARD_PAGE_CAP = 8


class InterviewGuidePdfOverflowError(RuntimeError):
    """Interview guide rendered more pages than the spec hard cap (8)."""


@register("interview_guide", "pdf")
class InterviewGuidePdfExporter(ExporterBase):
    artifact_type = "interview_guide"
    format = "pdf"

    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        html, builder = _build_html(payload, firm_branding, citations)

        primary = _normalise_hex(
            (firm_branding or {}).get("primary_color"), _DEFAULT_PRIMARY_HEX,
        )
        firm_name = builder.firm_name
        engagement_title = (
            builder.engagement_title or builder.target_name or "Argus engagement"
        )

        print_css = (
            page_header_footer_css(
                firm_name=firm_name,
                engagement_title=engagement_title,
                primary_hex=primary,
                muted_hex=_DEFAULT_MUTED_HEX,
            )
            + page_break_css()
        )

        pdf_bytes = _pdf_helpers.html_to_pdf(html, extra_css=[print_css])
        pages = _pdf_helpers.pdf_page_count(pdf_bytes)

        if pages > _INTERVIEW_PDF_HARD_PAGE_CAP:
            raise InterviewGuidePdfOverflowError(
                f"interview_guide_pdf_overflow: rendered {pages} pages, "
                f"cap is {_INTERVIEW_PDF_HARD_PAGE_CAP}. Reduce question "
                f"count or shorten 'why_asking' / 'follow_up_probe' prose."
            )

        return ExporterResult(
            file_bytes=pdf_bytes,
            file_size=len(pdf_bytes),
            claim_citation_count=builder.citation_count,
            metadata={
                "format_subtype": "pdf",
                "mode": builder.mode,
                "question_count": builder.question_count,
                "section_a_count": len(builder.section_a),
                "section_b_count": len(builder.section_b),
                "section_c_count": len(builder.section_c),
                "cited_claim_ids": list(builder.cited_claim_ids),
                "page_count": pages,
                "firm_name": firm_name,
            },
        )


__all__ = [
    "InterviewGuideHtmlExporter",
    "InterviewGuideMarkdownExporter",
    "InterviewGuidePdfExporter",
    "InterviewGuidePdfOverflowError",
]
