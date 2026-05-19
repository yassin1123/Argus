"""Excel sheet builders — W12.

Importing this package triggers registration of every concrete sheet
builder via ``@register_sheet``. Day 1 ships title + assumptions.
Days 2-3 add revenue_build, cost_build, dcf, comparables, sensitivity.
"""

from __future__ import annotations

from ._base import SheetBuilderBase, SheetResult  # noqa: F401
from ._registry import (  # noqa: F401
    get_sheet_builder,
    list_registered_sheets,
    register_sheet,
)
from .sequences import get_workbook_sheets_for_mode  # noqa: F401

# Importing concrete sheet modules registers them.
# Day 1 base pair:
from . import assumptions  # noqa: F401,E402
from . import title  # noqa: F401,E402

# Day 2 projection sheets:
from . import cost_build  # noqa: F401,E402
from . import revenue_build  # noqa: F401,E402

__all__ = [
    "SheetBuilderBase",
    "SheetResult",
    "get_sheet_builder",
    "get_workbook_sheets_for_mode",
    "list_registered_sheets",
    "register_sheet",
]
