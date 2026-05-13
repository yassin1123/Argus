"""Slide builder registry — W11/D1.

Mirrors the top-level exporter registry pattern (see
``core/exports/_registry.py``). Slide modules self-register via
``@register_slide(name)`` on the class.
"""

from __future__ import annotations

from typing import TypeVar

from ._base import SlideBuilderBase

_SLIDE_BUILDERS: dict[str, type[SlideBuilderBase]] = {}

T = TypeVar("T", bound=type[SlideBuilderBase])


def register_slide(name: str):
    """Decorator: register a slide builder class under ``name``.

    Sets ``cls.slide_name`` so the class doesn't need to declare it
    separately. Re-registration overwrites — intentional, so tests
    can swap.
    """

    def decorator(cls: T) -> T:
        cls.slide_name = name
        _SLIDE_BUILDERS[name] = cls
        return cls

    return decorator


def get_slide_builder(name: str) -> type[SlideBuilderBase]:
    if name not in _SLIDE_BUILDERS:
        raise KeyError(
            f"no slide builder registered for {name!r}; "
            f"available: {sorted(_SLIDE_BUILDERS.keys())}"
        )
    return _SLIDE_BUILDERS[name]


def list_registered_slides() -> list[str]:
    return sorted(_SLIDE_BUILDERS.keys())
