"""Export pipeline — W10/D2 foundation.

Public surface:
- :class:`ExporterBase` / :class:`ExporterResult` — abstract base + return shape.
- :func:`register` / :func:`get_exporter` — exporter registry.
- :func:`generate_artifact` — service entry point used by the API.
- :class:`GenerateArtifactRequest` / :class:`GenerateArtifactResult`.

Concrete exporters live in submodules (one_pager.py, memo.py, ...) and
self-register via the ``@register(artifact_type, format)`` decorator.
Importing this package triggers their registration as a side effect.
"""

from __future__ import annotations

from ._base import ClaimCitation, ExporterBase, ExporterResult
from ._registry import get_exporter, list_registered, register
from .service import (
    ArtifactNotFoundError,
    GenerateArtifactRequest,
    GenerateArtifactResult,
    artifact_file_path,
    generate_artifact,
    get_artifact,
    list_artifacts,
)

# Importing the concrete exporters here is what populates the registry.
# Keep the import after the registry symbols so circular-import is safe.
from . import one_pager  # noqa: F401,E402
from . import deck_pptx  # noqa: F401,E402
from . import excel_model  # noqa: F401,E402

__all__ = [
    "ArtifactNotFoundError",
    "ClaimCitation",
    "ExporterBase",
    "ExporterResult",
    "GenerateArtifactRequest",
    "GenerateArtifactResult",
    "artifact_file_path",
    "generate_artifact",
    "get_artifact",
    "get_exporter",
    "list_artifacts",
    "list_registered",
    "register",
]
