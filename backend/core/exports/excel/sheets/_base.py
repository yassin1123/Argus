"""Sheet builder base + result — W12/D1.

Each sheet builder produces ONE worksheet on the shared
``openpyxl.Workbook``. Builders are pure-ish: they side-effect the
workbook (the point) but do no IO. The renderer doesn't know about
specific sheet types, only sheet names ('title', 'assumptions',
...) keyed against the registry.

Parallel structure to the deck slide builders (W11/D1) so the two
exporters share a recognisable shape — adding a new sheet (DCF,
Comparables, Sensitivity) on Days 2-3 is one new file + one
sequence entry, same as adding a deck slide.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openpyxl import Workbook

    from ..._base import ClaimCitation
    from .._refs import CellRegistry


@dataclass
class SheetResult:
    """What a sheet builder returns to ``WorkbookBuilder``.

    ``sheet_index`` is the 0-indexed position in the workbook (matches
    ``Workbook.worksheets`` order). ``citation_ids`` accumulates every
    claim_id attached as a cell-comment on this sheet so the
    workbook-level diagnostics + the W12/D4 citation register can
    cross-reference. ``cell_count`` is a coarse diagnostic for the
    eval runner.
    """

    sheet_index: int
    citation_ids: list[str] = field(default_factory=list)
    cell_count: int = 0
    # W12/D4: opt out of the firm-header post-pass (Cover + Summary
    # own their top rows explicitly).
    skip_branding_header: bool = False


class SheetBuilderBase(ABC):
    """All sheet builders subclass this. Stateless (one instance per
    render is fine) and side-effects the workbook passed in."""

    sheet_name: str = ""  # the workbook tab name

    @abstractmethod
    def build(
        self,
        workbook: "Workbook",
        payload: Any,
        firm_branding: dict[str, Any],
        citations: "list[ClaimCitation]",
        cell_registry: "CellRegistry | None" = None,
    ) -> SheetResult:
        """Build the sheet onto ``workbook``.

        W12/D2: ``cell_registry`` is the per-workbook named-cell store
        threaded by :class:`WorkbookBuilder`. Sheet builders that
        produce reference targets (Assumptions writes ``wacc`` / per-year
        growth rows) call :meth:`CellRegistry.set` so downstream sheets
        (Revenue Build / Cost Build / DCF) can resolve those names
        into stable cross-sheet formulas via :meth:`CellRegistry.require`
        without baking row coordinates into multiple files.
        """
        raise NotImplementedError
