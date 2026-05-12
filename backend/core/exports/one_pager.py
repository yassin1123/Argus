"""One-pager HTML exporter — W10/D2 stub.

Day 2 ships a minimal HTML page with just the recommendation so the
end-to-end POST → render → persist → download round-trips. Day 3
fills in the full 1-pager (top-3 reasons, top-3 risks, decision
criteria, kill criteria) with branding applied.
"""

from __future__ import annotations

from html import escape
from typing import Any

from ._base import ClaimCitation, ExporterBase, ExporterResult, payload_get
from ._registry import register


@register("one_pager", "html")
class OnePagerHtmlExporter(ExporterBase):
    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        recommendation = str(payload_get(payload, "recommendation", default=""))
        primary = str(firm_branding.get("primary_color") or "#0F6E56")
        footer = str(firm_branding.get("footer_text") or "")

        html = (
            "<!doctype html>\n"
            "<html lang=\"en\">\n"
            "<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<title>One-pager (stub)</title>\n"
            f"<style>body{{font-family:sans-serif;margin:2rem;color:#1B1F23}} "
            f"h1{{color:{escape(primary)}}}</style>\n"
            "</head>\n"
            "<body>\n"
            "<h1>" + escape(recommendation) + "</h1>\n"
            "<p><em>W10/D2 stub — full 1-pager renders on Day 3.</em></p>\n"
            + (f"<footer>{escape(footer)}</footer>\n" if footer else "")
            + "</body>\n</html>\n"
        )
        b = html.encode("utf-8")
        return ExporterResult(
            file_bytes=b,
            file_size=len(b),
            claim_citation_count=0,
            metadata={"stub": True, "rendered_chars": len(html)},
        )
