"""Email exporters — markdown (W13/D1) + HTML (W13/D1).

Two formats today: markdown (paste into mail client) + HTML (rich
preview / direct-send). Both share the same :class:`EmailBuilder` —
the HTML exporter just runs the markdown body through
``markdown-it-py`` and wraps the result in a firm-branded shell.

Mode-aware (M&A talks deal terms; growth_strategy talks market
context). Firm-branded via the partner signature block + firm footer.
No inline citation markers in the body — the "Sources" line at the
bottom points to the attached memo for the full registry.

Reserved underscore-prefixed payload keys consumed by the builder:
  - ``_engagement_title``: e.g. "TargetCo diligence"
  - ``_target_name``: e.g. "TargetCo Holdings" — drives subject + lede
  - ``_firm_name``: overrides the firm_branding default
  - ``_partner_name``: defaults to "[Partner name]" placeholder
  - ``_partner_title``: defaults to "Partner"
  - ``_attached_artifacts``: optional list[str | dict] — overrides the
    mode-default bundle. Dict items take {label, detail} or {name, format}.
  - ``_mode_hint``: overrides the explicit ``mode`` field for dispatch.
"""

from __future__ import annotations

from typing import Any

from . import _pdf_helpers
from ._base import ClaimCitation, ExporterBase, ExporterResult
from ._pdf_helpers import PdfRuntimeError as _SharedPdfRuntimeError
from ._registry import register
from .email_builder import EmailBuilder

# Default firm primary colour (matches HEADING_TEXT_HEX in the excel
# styles module). Used when firm_branding doesn't supply one.
_DEFAULT_PRIMARY = "#0F6E56"
_DEFAULT_TEXT = "#1B1F23"
_DEFAULT_MUTED = "#5B6470"
_DEFAULT_BG = "#FFFFFF"


def _normalise_hex(raw: Any, default: str) -> str:
    if isinstance(raw, str):
        s = raw.strip()
        if not s.startswith("#"):
            s = "#" + s.lstrip("#")
        if len(s) == 7 and all(c in "0123456789abcdefABCDEF" for c in s[1:]):
            return s
    return default


def _markdown_to_html(md: str) -> str:
    """Render markdown body to HTML via markdown-it-py (already in
    deps). Stops short of producing a full document; the calling
    HTML exporter wraps this in the branded shell."""
    from markdown_it import MarkdownIt

    mdit = MarkdownIt("commonmark", {"breaks": True, "linkify": False})
    return mdit.render(md)


def _wrap_html(body_html: str, *, primary_hex: str, firm_name: str, subject: str) -> str:
    """Wrap the markdown-rendered body in a firm-branded HTML shell.

    Inline styles only — email clients strip <style> blocks
    inconsistently. The primary colour drives the H1/H2 headings;
    body text uses a neutral charcoal. No images are embedded
    (per hard rule: email clients render images inconsistently —
    firm name lives in the signature as text).
    """
    primary = _normalise_hex(primary_hex, _DEFAULT_PRIMARY)
    # Inject primary-colour styles by post-processing the markdown HTML.
    # markdown-it emits plain <h1>/<h2>/<strong>; we rewrite to inline-styled
    # variants so email clients pick the firm colour up without a <style> block.
    styled = body_html
    styled = styled.replace(
        "<h1>", f'<h1 style="color:{primary};font-family:Georgia,serif;font-size:18pt;'
        'margin:0 0 12px 0;line-height:1.3;">'
    )
    styled = styled.replace(
        "<h2>", f'<h2 style="color:{primary};font-family:Georgia,serif;font-size:14pt;'
        'margin:18px 0 8px 0;line-height:1.3;">'
    )
    styled = styled.replace(
        "<h3>", f'<h3 style="color:{primary};font-family:Georgia,serif;font-size:12pt;'
        'margin:14px 0 6px 0;line-height:1.3;">'
    )
    styled = styled.replace(
        "<strong>", f'<strong style="color:{primary};font-weight:600;">'
    )
    styled = styled.replace(
        "<em>", f'<em style="color:{_DEFAULT_MUTED};font-style:italic;">'
    )
    styled = styled.replace(
        "<p>",
        '<p style="font-family:Georgia,serif;font-size:11pt;line-height:1.55;'
        f'color:{_DEFAULT_TEXT};margin:0 0 12px 0;">'
    )
    styled = styled.replace(
        "<ol>",
        '<ol style="font-family:Georgia,serif;font-size:11pt;line-height:1.55;'
        f'color:{_DEFAULT_TEXT};margin:0 0 12px 22px;padding:0;">'
    )
    styled = styled.replace(
        "<ul>",
        '<ul style="font-family:Georgia,serif;font-size:11pt;line-height:1.55;'
        f'color:{_DEFAULT_TEXT};margin:0 0 12px 22px;padding:0;">'
    )
    styled = styled.replace(
        "<hr>",
        f'<hr style="border:0;border-top:1px solid {_DEFAULT_MUTED};margin:18px 0;">'
    )
    styled = styled.replace(
        "<hr />",
        f'<hr style="border:0;border-top:1px solid {_DEFAULT_MUTED};margin:18px 0;" />'
    )

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{subject}</title>
</head>
<body style="margin:0;padding:24px;background:{_DEFAULT_BG};color:{_DEFAULT_TEXT};">
  <div style="max-width:640px;margin:0 auto;background:{_DEFAULT_BG};">
    {styled}
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Markdown exporter
# ---------------------------------------------------------------------------


@register("email", "md")
class EmailMarkdownExporter(ExporterBase):
    artifact_type = "email"
    format = "md"

    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        builder = EmailBuilder(payload, firm_branding, citations)
        md = builder.build_markdown()
        encoded = md.encode("utf-8")
        return ExporterResult(
            file_bytes=encoded,
            file_size=len(encoded),
            claim_citation_count=builder.citation_count,
            metadata={
                "format_subtype": "markdown",
                "mode": builder.mode,
                "subject": builder.build_subject(),
                "cited_claim_ids": list(builder.cited_claim_ids),
                "body_word_count": _word_count(md),
            },
        )


# ---------------------------------------------------------------------------
# HTML exporter
# ---------------------------------------------------------------------------


@register("email", "html")
class EmailHtmlExporter(ExporterBase):
    artifact_type = "email"
    format = "html"

    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        builder = EmailBuilder(payload, firm_branding, citations)
        md = builder.build_markdown()
        body_html = _markdown_to_html(md)
        primary = _normalise_hex(
            (firm_branding or {}).get("primary_color"), _DEFAULT_PRIMARY
        )
        html = _wrap_html(
            body_html,
            primary_hex=primary,
            firm_name=builder.firm_name,
            subject=builder.build_subject(),
        )
        encoded = html.encode("utf-8")
        return ExporterResult(
            file_bytes=encoded,
            file_size=len(encoded),
            claim_citation_count=builder.citation_count,
            metadata={
                "format_subtype": "html",
                "mode": builder.mode,
                "subject": builder.build_subject(),
                "cited_claim_ids": list(builder.cited_claim_ids),
                "primary_color": primary,
                "body_word_count": _word_count(md),
            },
        )


# ---------------------------------------------------------------------------
# PDF exporter (W13/D2)
# ---------------------------------------------------------------------------


# A4 page with generous margins — the email body should breathe, not
# crash the page edge. Cover-email PDFs are reading material, not data
# dumps, so we trade density for line-height.
_EMAIL_PRINT_CSS = """
@page { size: A4; margin: 18mm; }
@media print {
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  strong { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
.page { max-height: calc(297mm - 36mm); overflow: hidden; }
"""

_TRUNCATION_SUFFIX_HTML = (
    '<p style="font-family:Georgia,serif;font-size:9pt;line-height:1.4;'
    'color:#5B6470;margin:12px 0 0 0;font-style:italic;">'
    "… [body truncated; see markdown version for the full email].</p>"
)


class EmailPdfRuntimeError(RuntimeError):
    """WeasyPrint's runtime (pango/cairo/gdk-pixbuf) isn't loadable.

    Distinct from :class:`EmailPdfOverflowError` so the service layer
    can tell environment issues apart from content overflow.
    """


class EmailPdfOverflowError(RuntimeError):
    """Email body can't fit on a single A4 page even after truncation."""


def _html_to_pdf(html: str) -> bytes:
    """W13/D4 — delegates to the shared ``_pdf_helpers.html_to_pdf``
    wrapper so the email PDF path and the interview-guide PDF path
    share one WeasyPrint integration point. Existing tests patch this
    symbol on this module, so it stays in place as a forwarder."""
    try:
        return _pdf_helpers.html_to_pdf(html, extra_css=[_EMAIL_PRINT_CSS])
    except _SharedPdfRuntimeError as e:
        raise EmailPdfRuntimeError(str(e)) from e


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """W13/D4 — delegates to ``_pdf_helpers.pdf_page_count`` while
    preserving the existing module-local symbol that tests patch."""
    return _pdf_helpers.pdf_page_count(pdf_bytes)


def _truncate_body_html(html: str) -> str:
    """Trim the rendered email HTML by dropping the recommendation +
    caveat paragraphs' tail sentences. Each <p> is shortened to its
    first sentence; the final paragraph gains the truncation suffix.

    The signature + sources/footer block (after the <hr>) is
    preserved verbatim — the consultant still needs the sign-off
    even when the body is trimmed.
    """
    import re as _re

    # Split on the horizontal-rule (rendered as <hr ...> or <hr/>) so
    # we can preserve the post-rule footer block unchanged.
    hr_match = _re.search(r"<hr[^>]*>", html, flags=_re.IGNORECASE)
    if hr_match:
        head = html[: hr_match.start()]
        tail = html[hr_match.start():]
    else:
        head, tail = html, ""

    # Shorten each <p> in the head to its first sentence.
    def _shorten(m: _re.Match[str]) -> str:
        attrs = m.group(1) or ""
        inner = m.group(2) or ""
        # Strip child tags for the sentence-split (keep them in the
        # final output of the first sentence).
        plain = _re.sub(r"<[^>]+>", "", inner)
        first_sentence_split = _re.split(r"(?<=[.!?])\s+", plain.strip(), maxsplit=1)
        if not first_sentence_split:
            return m.group(0)
        first = first_sentence_split[0]
        if not first:
            return m.group(0)
        return f"<p{attrs}>{first}</p>"

    shortened = _re.sub(r"<p([^>]*)>(.*?)</p>", _shorten, head, flags=_re.DOTALL)

    # Drop <ol>/<ul> attachments — they consume vertical space and the
    # markdown version preserves them.
    shortened = _re.sub(r"<(ol|ul)[^>]*>.*?</\1>", "", shortened, flags=_re.DOTALL | _re.IGNORECASE)

    return shortened + _TRUNCATION_SUFFIX_HTML + tail


@register("email", "pdf")
class EmailPdfExporter(ExporterBase):
    artifact_type = "email"
    format = "pdf"

    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        html_result = await EmailHtmlExporter().render(payload, firm_branding, citations)
        html = html_result.file_bytes.decode("utf-8")

        # Attempt 1: full body.
        pdf_bytes = _html_to_pdf(html)
        pages = _pdf_page_count(pdf_bytes)
        attempt_meta: dict[str, Any] = {
            "attempt_1_pages": pages,
            "truncated_for_fit": False,
        }
        if pages != 1:
            # Attempt 2: truncated body. The W13/D1 builder caps the
            # email at 250 words, so this branch is rare — only fires
            # on payloads with overly long key_reasons / risks prose
            # that pushed the rendered email onto a second page.
            attempt_meta["truncated_for_fit"] = True
            truncated_html = _truncate_body_html(html)
            pdf_bytes = _html_to_pdf(truncated_html)
            pages_retry = _pdf_page_count(pdf_bytes)
            attempt_meta["attempt_2_pages"] = pages_retry
            if pages_retry != 1:
                raise EmailPdfOverflowError(
                    f"email_pdf_overflow_after_truncation: "
                    f"attempt 1 = {pages} page(s), attempt 2 = {pages_retry} page(s)"
                )
            pages = pages_retry

        return ExporterResult(
            file_bytes=pdf_bytes,
            file_size=len(pdf_bytes),
            claim_citation_count=html_result.claim_citation_count,
            metadata={
                **{k: v for k, v in (html_result.metadata or {}).items()
                   if k != "format_subtype"},
                "format_subtype": "pdf",
                "page_count": pages,
                **attempt_meta,
            },
        )


def _word_count(text: str) -> int:
    """Word count of the markdown body, excluding the signature /
    sources / confidentiality lines. The spec's 250-word cap measures
    the body — the post-`---` zone is metadata/legal."""
    head = text.split("\n---", 1)[0]
    # Strip "Best regards," through end of paragraph (signature block lives there).
    parts = head.split("Best regards,", 1)
    body = parts[0] if len(parts) > 1 else head
    return len([w for w in body.split() if w.strip()])


__all__ = [
    "EmailHtmlExporter",
    "EmailMarkdownExporter",
    "EmailPdfExporter",
    "EmailPdfOverflowError",
    "EmailPdfRuntimeError",
]
