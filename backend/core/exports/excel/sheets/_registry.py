"""Sheet builder registry — W12/D1.

Parallels the deck slide-builder registry (W11) and the top-level
exporter registry (W10). Sheet modules self-register via
``@register_sheet(name)`` on the class.
"""

from __future__ import annotations

from typing import TypeVar

from ._base import SheetBuilderBase

_SHEET_BUILDERS: dict[str, type[SheetBuilderBase]] = {}

T = TypeVar("T", bound=type[SheetBuilderBase])


def register_sheet(name: str):
    """Decorator: register a sheet-builder class under ``name``.

    Sets ``cls.sheet_name`` so subclasses don't need to declare it
    separately. Re-registration overwrites (intentional — tests swap).
    """

    def decorator(cls: T) -> T:
        cls.sheet_name = name
        _SHEET_BUILDERS[name] = cls
        return cls

    return decorator


def get_sheet_builder(name: str) -> type[SheetBuilderBase]:
    if name not in _SHEET_BUILDERS:
        raise KeyError(
            f"no sheet builder registered for {name!r}; "
            f"available: {sorted(_SHEET_BUILDERS.keys())}"
        )
    return _SHEET_BUILDERS[name]


def list_registered_sheets() -> list[str]:
    return sorted(_SHEET_BUILDERS.keys())
