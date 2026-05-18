"""Excel financial model exporter — W12/D1.

Top-level shim that plugs the workbook builder into the W10 exporter
registry. Mirrors deck_pptx.py from W11. The heavy lifting lives
under ``core/exports/excel/`` so this file stays small and only
changes when sequences / metadata fields shift.
"""

from __future__ import annotations

from typing import Any

from ._base import ClaimCitation, ExporterBase, ExporterResult, payload_get
from ._registry import register
from .excel import WorkbookBuilder, get_workbook_sheets_for_mode
from .one_pager_renderer import _detect_mode


@register("excel_model", "xlsx")
class ExcelModelExporter(ExporterBase):
    """Render a starting financial model as a .xlsx via openpyxl.

    Mode-aware sequence: M&A / growth / general share a 2-sheet
    minimum on Day 1 (title + assumptions). Days 2-3 add the model
    sheets without touching this class — only ``sequences.py`` and
    the sheet registry grow.
    """

    artifact_type = "excel_model"
    format = "xlsx"

    async def render(
        self,
        payload: Any,
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        mode_hint = payload_get(payload, "_mode_hint", default=None)
        mode = _detect_mode(payload, mode_hint)
        sequence = get_workbook_sheets_for_mode(mode)

        builder = WorkbookBuilder(payload, firm_branding or {}, citations or [])
        for sheet_name in sequence:
            builder.add_sheet(sheet_name)
        xlsx_bytes = builder.serialize()

        return ExporterResult(
            file_bytes=xlsx_bytes,
            file_size=len(xlsx_bytes),
            claim_citation_count=builder.citation_count,
            metadata={
                "mode": mode,
                "sheet_count": builder.sheet_count,
                "sheet_sequence": sequence,
                "cited_claim_ids": builder.cited_claim_ids,
            },
        )
