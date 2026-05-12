"""One-pager HTML exporter — W10/D3 full renderer.

Replaces the W10/D2 stub. Mode-aware (M&A valuation row, growth_strategy
Porter's row), firm-branded via CSS variables, citation-preserving via
``data-claim-id`` chips at the bottom. No JavaScript — the HTML is
print-ready for D4's PDF conversion.

Engagement metadata (title, target, prepared-by, mode hint, firm name)
travels in via reserved underscore-prefixed keys on the payload dict
(``_engagement_title``, ``_target_name``, ``_prepared_by``,
``_mode_hint``, ``_firm_name``). The service layer injects these
before calling render; tests can set them directly when needed.

Templates live under ``templates/one_pager/`` and are loaded once into
a module-level Jinja environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ._base import ClaimCitation, ExporterBase, ExporterResult, payload_get
from ._registry import register
from .one_pager_renderer import build_one_pager_context

_TEMPLATE_DIR = Path(__file__).parent / "templates" / "one_pager"
_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


@register("one_pager", "html")
class OnePagerHtmlExporter(ExporterBase):
    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
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
        )
        html = _ENV.get_template("base.html.j2").render(**ctx)
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
