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

from .sheets import get_sheet_builder, list_registered_sheets  # noqa: F401
from .sheets._base import SheetResult


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

    def add_sheet(self, sheet_name: str) -> SheetResult:
        builder_cls = get_sheet_builder(sheet_name)
        builder = builder_cls()
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

    def serialize(self) -> bytes:
        buf = io.BytesIO()
        self._workbook.save(buf)
        return buf.getvalue()
