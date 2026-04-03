"""Jinja2 + WeasyPrint render for DeliverableDocument."""

import json
import re
from pathlib import Path
from typing import Any

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

from jinja2 import Environment, FileSystemLoader, select_autoescape

from deliverables.models import DeliverableDocument

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_BRAND_PATH = Path(__file__).resolve().parent / "brand_tokens.json"


def _load_brand_tokens() -> dict[str, Any]:
    if not _BRAND_PATH.is_file():
        return {
            "accent": "#6366f1",
            "text_primary": "#0f172a",
            "text_secondary": "#475569",
            "text_muted": "#64748b",
            "border": "#e2e8f0",
            "callout_border": "#6366f1",
            "surface": "#f8fafc",
        }
    return json.loads(_BRAND_PATH.read_text(encoding="utf-8"))


def render_deliverable_html(
    doc: DeliverableDocument,
    *,
    variant: str = "full",
    report: dict[str, Any] | None = None,
) -> str:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.get_template("deliverable.html.j2")
    ver_json = ""
    if variant == "memo" and report:
        ver = report.get("verification")
        if ver:
            raw = json.dumps(ver, ensure_ascii=False)[:12000]
            ver_json = _UUID_RE.sub("[id]", raw)
    brand = _load_brand_tokens()
    return tpl.render(
        doc=doc.model_dump(),
        variant=variant,
        verification_json=ver_json,
        brand=brand,
    )


def render_deliverable_pdf(
    doc: DeliverableDocument,
    *,
    variant: str = "full",
    report: dict[str, Any] | None = None,
) -> bytes:
    from weasyprint import HTML

    html_str = render_deliverable_html(doc, variant=variant, report=report)
    return HTML(string=html_str).write_pdf()
