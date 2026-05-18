"""Excel financial-model exporter package — W12.

Public surface for everything outside ``core/exports/`` is the
``ExcelModelExporter`` registered against ``('excel_model', 'xlsx')``
via the top-level exports registry. ``WorkbookBuilder`` and the
sheet-registry machinery are exposed for tests + future formats.
"""

from __future__ import annotations

from .sheets import (
    SheetBuilderBase,
    SheetResult,
    get_sheet_builder,
    get_workbook_sheets_for_mode,
    list_registered_sheets,
    register_sheet,
)
from .workbook_builder import WorkbookBuilder

__all__ = [
    "SheetBuilderBase",
    "SheetResult",
    "WorkbookBuilder",
    "get_sheet_builder",
    "get_workbook_sheets_for_mode",
    "list_registered_sheets",
    "register_sheet",
]
