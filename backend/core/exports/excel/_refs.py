"""Cross-sheet cell-reference helpers — W12/D2.

The Revenue Build / Cost Build / DCF sheets need to reference cells
on the Assumptions sheet (and each other). Hardcoding ``Assumptions!B14``
into every formula is fragile — the row drifts whenever the
Assumptions layout changes. So sheet builders register their output
cells against a named registry on the WorkbookBuilder, and downstream
sheet builders resolve names to qualified refs at write time.

Public surface:
  - :func:`cell_ref(sheet_name, cell)` — quote sheet name if needed,
    produce a sheet-qualified reference (``'Revenue Build'!B5`` or
    ``Assumptions!B14``).
  - :func:`absolute_ref(sheet_name, cell)` — like above but with ``$``
    anchors on both row and column (e.g. ``Assumptions!$B$14``).
  - :class:`CellRegistry` — a dict-shaped store of named cell refs
    living on the WorkbookBuilder. Sheet builders write entries
    (``builder.refs.set("wacc", "Assumptions!B14")``) and read them
    later (``builder.refs.get("wacc")``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Excel quotes sheet names that contain spaces, slashes, or other
# non-alphanumeric characters. The minimum-correct rule: quote
# anything that doesn't match a plain identifier.
_SAFE_SHEET_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quote_sheet_name(sheet_name: str) -> str:
    """Quote the sheet name if Excel would need it quoted. Single
    quotes inside the name are doubled (``it's`` → ``'it''s'``)."""
    if _SAFE_SHEET_NAME.match(sheet_name):
        return sheet_name
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'"


def cell_ref(sheet_name: str, cell: str) -> str:
    """Produce a sheet-qualified cell reference.

    ``cell_ref("Assumptions", "B14")`` → ``"Assumptions!B14"``.
    ``cell_ref("Revenue Build", "C5")`` → ``"'Revenue Build'!C5"``.
    """
    return f"{_quote_sheet_name(sheet_name)}!{cell}"


def absolute_ref(sheet_name: str, cell: str) -> str:
    """Same as :func:`cell_ref` but with absolute row + column anchors
    (``$B$14``). Used for assumption cells that downstream formulas
    must not have shift when copy-pasted in Excel."""
    # Split row vs column letters.
    m = re.match(r"^([A-Za-z]+)(\d+)$", cell)
    if not m:
        return cell_ref(sheet_name, cell)
    col, row = m.group(1), m.group(2)
    return f"{_quote_sheet_name(sheet_name)}!${col}${row}"


@dataclass
class CellRegistry:
    """Named cell-ref store carried on :class:`WorkbookBuilder`.

    Sheet builders write entries when they place a cell another sheet
    will reference (the Assumptions sheet stamps ``"wacc"``,
    ``"terminal_growth"``, ``"revenue_growth_y1"``, etc.). Downstream
    sheets read entries with :meth:`get` and produce stable formulas.

    The registry stores absolute refs by default so formulas placed
    on the consuming sheet won't drift if Excel copies them around.
    """

    refs: dict[str, str] = field(default_factory=dict)

    def set(self, name: str, sheet: str, cell: str, *, absolute: bool = True) -> str:
        """Register a named cell. Returns the qualified ref."""
        if absolute:
            ref = absolute_ref(sheet, cell)
        else:
            ref = cell_ref(sheet, cell)
        self.refs[name] = ref
        return ref

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.refs.get(name, default)

    def require(self, name: str) -> str:
        """Like :meth:`get` but raises ``KeyError`` if missing. Used when
        a downstream sheet would render incorrectly without the ref."""
        if name not in self.refs:
            raise KeyError(
                f"required cell reference {name!r} not registered "
                f"(available: {sorted(self.refs.keys())})"
            )
        return self.refs[name]

    def keys(self) -> list[str]:
        return sorted(self.refs.keys())


# Standard Excel number formats — wired into every sheet builder so
# the workbook reads as a real consulting model.
NUMBER_FORMATS = {
    "currency_gbp_m":  '"£"#,##0.0;("£"#,##0.0);"–"',
    "currency_gbp":    '"£"#,##0;("£"#,##0);"–"',
    "percent":         "0.0%",
    "multiple":        '0.0"x"',
    "integer":         "#,##0",
    "year":            "0",
}


__all__ = [
    "NUMBER_FORMATS",
    "CellRegistry",
    "absolute_ref",
    "cell_ref",
]
