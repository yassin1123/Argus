"""WorkbookBuilder — wraps an ``openpyxl.Workbook``, dispatches per-sheet
builders by name, accumulates citation_ids across sheets, and
serializes the workbook to bytes.

Parallel structure to the W11 DeckBuilder so the two exporters
share a recognisable shape. Day 1 ships title + assumptions; the
remaining model sheets layer on via registry entries Days 2-3.
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook

from .._base import payload_get
from ._branding import add_firm_header, apply_tab_color, freeze_top_row
from ._refs import CellRegistry
from ._styles import HEADING_TEXT_HEX
from .sheets import get_sheet_builder, list_registered_sheets  # noqa: F401
from .sheets._base import SheetResult
from .sheets.sequences import SHEET_VISUAL_POSITION

# Display names for each sheet in the row-1 firm header band.
_SHEET_DISPLAY_NAMES: dict[str, str] = {
    "title":           "Cover",
    "summary":         "Summary",
    "assumptions":     "Assumptions",
    "revenue_build":   "Revenue Build",
    "cost_build":      "Cost Build",
    "working_capital": "Working Capital",
    "dcf":             "DCF",
    "comparables":     "Comparables",
    "sensitivity":     "Sensitivity",
    "synergies":       "Synergies",
}


class WorkbookBuilder:
    """Wraps a fresh ``openpyxl.Workbook``. Each ``add_sheet(name)``
    call looks the builder up in the sheet registry and runs it
    against the shared payload + branding + citations context."""

    def __init__(
        self,
        payload: Any,
        firm_branding: dict[str, Any] | None,
        citations: list[Any] | None,
    ) -> None:
        self._payload = payload
        self._branding = dict(firm_branding or {})
        self._citations = list(citations or [])

        self._workbook = Workbook()
        # openpyxl gives every new workbook a default 'Sheet'. Remove it
        # so the only worksheets in the file are the ones builders add.
        default = self._workbook.active
        if default is not None and default.title == "Sheet":
            self._workbook.remove(default)

        self._results: list[SheetResult] = []
        self._sheet_names_ordered: list[str] = []
        self._all_citation_ids: list[str] = []
        self._seen_citation_ids: set[str] = set()
        # W12/D2: named cell-ref registry that sheet builders share.
        # Assumptions writes ``wacc`` / ``revenue_growth_y1`` etc.;
        # Revenue Build + Cost Build read them to produce stable
        # cross-sheet formulas.
        self._refs = CellRegistry()

    @property
    def workbook(self) -> Workbook:
        return self._workbook

    @property
    def sheet_count(self) -> int:
        return len(self._workbook.worksheets)

    @property
    def citation_count(self) -> int:
        return len(self._all_citation_ids)

    @property
    def cited_claim_ids(self) -> list[str]:
        return list(self._all_citation_ids)

    @property
    def sheet_names(self) -> list[str]:
        """Ordered registry-key names for each sheet. (The workbook
        also tracks Worksheet.title; these are the registry-side
        names used in sequences.py.)"""
        return list(self._sheet_names_ordered)

    @property
    def refs(self) -> CellRegistry:
        """Named cell-ref store shared across sheet builders."""
        return self._refs

    def add_sheet(self, sheet_name: str) -> SheetResult:
        builder_cls = get_sheet_builder(sheet_name)
        builder = builder_cls()
        # W12/D2: sheet builders that need cross-sheet refs accept a
        # ``cell_registry`` kwarg. Builders that don't reference it
        # use the kwarg default (None) and ignore it — keeps the
        # base ABC backwards-compatible with D1's title/assumptions.
        try:
            result = builder.build(
                self._workbook,
                self._payload,
                self._branding,
                self._citations,
                cell_registry=self._refs,
            )
        except TypeError:
            # Older builder signature (no cell_registry kwarg) — call
            # through the original 4-arg shape.
            result = builder.build(
                self._workbook,
                self._payload,
                self._branding,
                self._citations,
            )
        self._results.append(result)
        self._sheet_names_ordered.append(sheet_name)
        for cid in result.citation_ids:
            if cid and cid not in self._seen_citation_ids:
                self._seen_citation_ids.add(cid)
                self._all_citation_ids.append(cid)
        return result

    def _reorder_visual(self) -> None:
        """Move sheets whose registry name has a SHEET_VISUAL_POSITION
        override to their target visual index. openpyxl exposes
        ``_sheets`` for direct manipulation — we work on it carefully,
        preserving every other sheet's relative position.

        After reordering, refresh ``sheet_index`` on EVERY slot
        (build-order list ↔ visual-order list mapping) so the
        downstream branding pass walks the worksheets through the
        right slot result.
        """
        # Capture each slot's worksheet object BEFORE reordering so the
        # reference survives the move.
        slot_to_ws = {
            i: self._workbook.worksheets[slot.sheet_index]
            for i, slot in enumerate(self._results)
        }

        for sheet_name, target_idx in SHEET_VISUAL_POSITION.items():
            if sheet_name not in self._sheet_names_ordered:
                continue
            build_idx = self._sheet_names_ordered.index(sheet_name)
            ws = slot_to_ws[build_idx]
            try:
                sheets = list(self._workbook._sheets)
                sheets.remove(ws)
                target = min(target_idx, len(sheets))
                sheets.insert(target, ws)
                self._workbook._sheets = sheets
            except Exception:
                # Private API shifted; fall back to build order.
                pass

        # Refresh every slot.sheet_index against the new visual order
        # so finalize_branding's worksheets[slot.sheet_index] lookup
        # works.
        for build_idx, ws in slot_to_ws.items():
            try:
                self._results[build_idx].sheet_index = (
                    self._workbook.worksheets.index(ws)
                )
            except ValueError:
                pass

    def finalize_branding(self) -> None:
        """Apply firm-branding chrome (row-1 header + tab colour +
        freeze panes) on every sheet that didn't opt out.

        Runs after the sheet builders have placed their content so
        the chrome composes on top of fully-rendered sheets and the
        engagement title / firm name come from a single canonical
        source.
        """
        firm_name = (
            self._branding.get("_firm_name")
            or payload_get(self._payload, "_firm_name", default="Argus")
            or "Argus"
        )
        engagement_title = str(
            payload_get(self._payload, "_engagement_title", default="Argus engagement")
            or "Argus engagement"
        )
        primary_hex = str(
            self._branding.get("primary_color") or f"#{HEADING_TEXT_HEX}"
        )

        for i, slot in enumerate(self._results):
            ws = self._workbook.worksheets[slot.sheet_index]
            apply_tab_color(ws, primary_hex=primary_hex)
            if slot.skip_branding_header:
                continue
            sheet_key = self._sheet_names_ordered[i]
            display_name = _SHEET_DISPLAY_NAMES.get(sheet_key, sheet_key.replace("_", " ").title())
            add_firm_header(
                ws,
                firm_name=str(firm_name),
                sheet_display_name=display_name,
                engagement_title=engagement_title,
                primary_hex=primary_hex,
                last_data_col=max(ws.max_column, 6),
            )
            freeze_top_row(ws)

    def serialize(self) -> bytes:
        # Reorder before branding so the branding pass walks the
        # final visual sequence and applies header / tab colour / freeze
        # in the order the user will see them.
        self._reorder_visual()
        self.finalize_branding()
        buf = io.BytesIO()
        self._workbook.save(buf)
        return buf.getvalue()
