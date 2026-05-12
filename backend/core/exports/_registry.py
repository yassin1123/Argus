"""Exporter registry — W10/D2.

Maps ``(artifact_type, format)`` tuples to ``ExporterBase`` subclasses.
Exporters self-register via the ``@register`` decorator on the class.
"""

from __future__ import annotations

from typing import TypeVar

from ._base import ExporterBase

_REGISTRY: dict[tuple[str, str], type[ExporterBase]] = {}

T = TypeVar("T", bound=type[ExporterBase])


def register(artifact_type: str, format: str):
    """Decorator: register an exporter class against ``(type, format)``.

    Sets the class attributes ``artifact_type`` and ``format`` on the
    decorated class so subclasses don't have to duplicate them.
    Re-registration against the same key overwrites — this is
    deliberate so tests can swap exporters in/out.
    """

    def decorator(cls: T) -> T:
        cls.artifact_type = artifact_type
        cls.format = format
        _REGISTRY[(artifact_type, format)] = cls
        return cls

    return decorator


def get_exporter(artifact_type: str, format: str) -> ExporterBase | None:
    cls = _REGISTRY.get((artifact_type, format))
    if cls is None:
        return None
    return cls()


def list_registered() -> list[tuple[str, str]]:
    """Return all currently-registered ``(artifact_type, format)`` tuples,
    sorted. Used by tests and the API's debug surface."""
    return sorted(_REGISTRY.keys())
