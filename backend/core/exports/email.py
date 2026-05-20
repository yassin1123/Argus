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

from ._base import ClaimCitation, ExporterBase, ExporterResult
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


def _word_count(text: str) -> int:
    """Word count of the markdown body, excluding the signature /
    sources / confidentiality lines. The spec's 250-word cap measures
    the body — the post-`---` zone is metadata/legal."""
    head = text.split("\n---", 1)[0]
    # Strip "Best regards," through end of paragraph (signature block lives there).
    parts = head.split("Best regards,", 1)
    body = parts[0] if len(parts) > 1 else head
    return len([w for w in body.split() if w.strip()])


__all__ = ["EmailMarkdownExporter", "EmailHtmlExporter"]
