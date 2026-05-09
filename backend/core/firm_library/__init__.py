"""Firm-knowledge library (Phase 2 / Week 5).

Public API:
  - :func:`ingest_firm_content` — parse → chunk → embed → write firm-scoped chunks.
  - :func:`retire_firm_content` — soft-delete + retire chunks from retrieval.
"""

from core.firm_library.service import (
    FIRM_LIBRARY_SOURCE_TYPE,
    SUPPORTED_EXTENSIONS,
    UnsupportedFileTypeError,
    ingest_firm_content,
    retire_firm_content,
)

__all__ = [
    "FIRM_LIBRARY_SOURCE_TYPE",
    "SUPPORTED_EXTENSIONS",
    "UnsupportedFileTypeError",
    "ingest_firm_content",
    "retire_firm_content",
]
