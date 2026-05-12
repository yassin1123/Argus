"""Exporter abstract base + return shape — W10/D2."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ClaimCitation:
    """Lightweight citation shape passed into the exporter.

    Built by the service layer from the analyst's ``key_claims`` plus
    the session's evidence catalog, so the exporter does not need to
    rejoin against the DB to render footnotes / source pages.
    """

    claim_id: str
    text: str
    source_title: str = ""
    source_type: str = ""


@dataclass
class ExporterResult:
    """Return shape from a concrete exporter's ``render`` call.

    The service layer is responsible for persisting ``file_bytes`` to
    disk + writing the ``export_artifacts`` row. The exporter only
    produces bytes and the metadata that goes alongside them.
    """

    file_bytes: bytes
    file_size: int
    claim_citation_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class ExporterBase(ABC):
    """Abstract base for every artifact exporter.

    Subclasses declare their ``artifact_type`` + ``format`` as class
    attributes (the registry uses the tuple as the key) and implement
    ``render``.
    """

    artifact_type: str = ""
    format: str = ""

    @abstractmethod
    async def render(
        self,
        payload: Any,  # WriterReportBase subclass instance OR dict
        firm_branding: dict[str, Any],
        citations: list[ClaimCitation],
    ) -> ExporterResult:
        """Produce the artifact bytes.

        ``payload`` may arrive as a Pydantic ``WriterReportBase`` (or
        subclass) or as a plain dict (when the caller has already
        serialized). Concrete exporters should be tolerant of both
        — use ``_payload_get(payload, "recommendation")`` helpers.
        """
        raise NotImplementedError


def payload_get(payload: Any, *names: str, default: Any = "") -> Any:
    """Read an attribute or key from a Pydantic model or dict.

    Tries each name in order; returns the first non-empty hit, else
    ``default``. Used by exporters to be tolerant of payloads arriving
    in either object or dict form (the service layer hands the
    Pydantic instance; tests often pass dicts).
    """
    for name in names:
        if isinstance(payload, dict):
            v = payload.get(name)
        else:
            v = getattr(payload, name, None)
        if v is not None and v != "" and v != [] and v != {}:
            return v
    return default
