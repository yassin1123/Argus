"""Payload version history — Phase 4 / Week 19 / Day 1.

Formalises the snapshots W9 + W15 used to scatter across feature-
specific tables into one coherent history. Every meaningful change
to an engagement's payload becomes a versioned snapshot with
metadata: change_type, changed_section_paths, review_state at the
time, and the actor who triggered it.

Public surface:

  - :class:`ChangeType` — five-value enum.
  - :class:`PayloadVersion` / :class:`PayloadVersionSummary` —
    full + metadata-only result shapes.
  - :func:`create_version`, :func:`list_versions`,
    :func:`get_version`, :func:`get_current_version`,
    :func:`ensure_initial_version`.
  - :func:`changed_sections` — diff helper.
"""

from .diff import changed_sections
from .service import (
    PayloadVersion,
    PayloadVersionSummary,
    create_version,
    ensure_initial_version,
    get_current_version,
    get_version,
    list_versions,
)
from .types import ChangeType

__all__ = [
    "ChangeType",
    "PayloadVersion",
    "PayloadVersionSummary",
    "changed_sections",
    "create_version",
    "ensure_initial_version",
    "get_current_version",
    "get_version",
    "list_versions",
]
