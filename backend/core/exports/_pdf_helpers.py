"""Shared WeasyPrint helpers — W13/D4.

Additive utilities used by W13/D4 onward (email PDF, interview guide
PDF). The W10 one-pager PDF and W13/D2 email PDF predate this module
and continue to inline their own print CSS — per spec hard rule, we
DON'T refactor the W10 paths today.

Public surface:

  - :data:`PAGE_BREAK_CLASS` — the CSS class name multi-page artifacts
    apply to elements that should start on a fresh page.
  - :func:`page_break_css` — emits the ``page-break-before: always``
    rule for that class, plus orphan/widow safety.
  - :func:`page_header_footer_css` — emits a ``@page`` rule that runs
    a centred header (firm name + engagement title) and a left/right
    footer (confidentiality + page number) on every page.
  - :func:`html_to_pdf` — late-import wrapper around WeasyPrint's
    ``HTML(...).write_pdf(...)``, raising :class:`PdfRuntimeError` on
    missing native libs so the service layer can surface a useful
    failure reason instead of a stack trace.
  - :func:`pdf_page_count` — late-import wrapper around PyMuPDF's
    page-count call. Returns ``-1`` on parse failure.
"""

from __future__ import annotations

from typing import Any


PAGE_BREAK_CLASS = "argus-pdf-section-break"


class PdfRuntimeError(RuntimeError):
    """WeasyPrint's native runtime (pango / cairo / gdk-pixbuf) isn't
    loadable. Distinct from artifact-specific overflow errors so the
    service layer can surface install instructions vs content-too-big
    independently.
    """


def page_break_css(section_class: str = PAGE_BREAK_CLASS) -> str:
    """Return CSS that forces ``.section_class`` to start on a new
    page. Standard ``page-break-before`` works in WeasyPrint; the
    modern ``break-before`` is set alongside it for forward-compat.

    Also widens orphan/widow tolerance inside the broken section so
    short residual paragraphs don't trigger an extra page break.
    """
    return (
        f".{section_class} {{\n"
        f"  page-break-before: always;\n"
        f"  break-before: page;\n"
        f"  orphans: 3;\n"
        f"  widows: 3;\n"
        f"}}\n"
        f".{section_class}:first-of-type {{\n"
        f"  page-break-before: avoid;\n"
        f"  break-before: avoid;\n"
        f"}}\n"
    )


def page_header_footer_css(
    *,
    firm_name: str,
    engagement_title: str,
    confidentiality_text: str | None = None,
    primary_hex: str = "#0F6E56",
    muted_hex: str = "#5B6470",
) -> str:
    """Emit a ``@page`` rule with running header + footer.

    WeasyPrint supports CSS Paged Media level 3: named strings
    (``string-set: ... content()``) populated outside @page are
    pulled into the page chrome via ``string(...)``. We use a fixed
    header (firm name centred) + a footer (confidentiality on the
    left, page N of M on the right) — keeps the print chrome stable
    across the whole guide.
    """
    confidentiality = (
        confidentiality_text
        or f"Confidential — {firm_name}"
    )
    # Escape characters that would break the CSS literal.
    safe_firm = firm_name.replace("\\", "\\\\").replace('"', '\\"')
    safe_eng = engagement_title.replace("\\", "\\\\").replace('"', '\\"')
    safe_conf = confidentiality.replace("\\", "\\\\").replace('"', '\\"')
    return (
        "@page {\n"
        "  size: A4;\n"
        "  margin: 18mm 18mm 22mm 18mm;\n"
        "  @top-center {\n"
        f"    content: \"{safe_firm}  —  {safe_eng}\";\n"
        f"    color: {muted_hex};\n"
        "    font-family: Georgia, serif;\n"
        "    font-size: 9pt;\n"
        "  }\n"
        "  @bottom-left {\n"
        f"    content: \"{safe_conf}\";\n"
        f"    color: {muted_hex};\n"
        "    font-family: Georgia, serif;\n"
        "    font-size: 8pt;\n"
        "  }\n"
        "  @bottom-right {\n"
        "    content: \"Page \" counter(page) \" of \" counter(pages);\n"
        f"    color: {muted_hex};\n"
        "    font-family: Georgia, serif;\n"
        "    font-size: 8pt;\n"
        "  }\n"
        "}\n"
        "@media print {\n"
        f"  body {{ color: #1B1F23; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}\n"
        f"  h1, h2 {{ color: {primary_hex}; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}\n"
        "}\n"
    )


def html_to_pdf(html: str, extra_css: list[str] | None = None) -> bytes:
    """Render ``html`` to PDF via WeasyPrint with optional extra CSS.

    Late-imports WeasyPrint so the rest of the export pipeline loads
    even when the native runtime is missing (Windows dev hosts).
    """
    try:
        from weasyprint import CSS, HTML  # type: ignore
    except (ImportError, OSError) as e:  # pragma: no cover
        raise PdfRuntimeError(
            f"WeasyPrint runtime not available: {e}. "
            f"Install pango/cairo/gdk-pixbuf system libs "
            f"(see backend/core/exports/README.md) or run inside Docker."
        ) from e
    sheets = [CSS(string=block) for block in (extra_css or []) if block]
    return HTML(string=html).write_pdf(stylesheets=sheets)


def pdf_page_count(pdf_bytes: bytes) -> int:
    """Return the number of pages in ``pdf_bytes`` via PyMuPDF.
    Returns ``-1`` on a parse failure so callers can surface the
    error rather than silently assume 1.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:  # pragma: no cover
        return 1
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001
        return -1


__all__ = [
    "PAGE_BREAK_CLASS",
    "PdfRuntimeError",
    "html_to_pdf",
    "page_break_css",
    "page_header_footer_css",
    "pdf_page_count",
]
