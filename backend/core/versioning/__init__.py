"""Payload version history — Phase 4 / Week 19 / Day 1+D2.

Formalises the snapshots W9 + W15 used to scatter across feature-
specific tables into one coherent history. Every meaningful change
to an engagement's payload becomes a versioned snapshot with
metadata: change_type, changed_section_paths, review_state at the
time, and the actor who triggered it.

D2 adds the diff + restore surfaces — let the user compare any
two versions and roll back to an earlier one (history is
append-only; restore creates a NEW current version equal to the
target).

Public surface:

  - :class:`ChangeType` — five-value enum.
  - :class:`PayloadVersion` / :class:`PayloadVersionSummary` —
    full + metadata-only result shapes.
  - :func:`create_version`, :func:`list_versions`,
    :func:`get_version`, :func:`get_current_version`,
    :func:`ensure_initial_version`.
  - :func:`changed_sections` — section-name diff helper.
  - :class:`VersionDiff`, :class:`SectionChange`, :class:`DiffSegment`,
    :func:`diff_versions` — W19/D2 word-level + claim diff.
  - :class:`RestoreResult`, :func:`restore_version` — W19/D2
    approval-aware restore.
"""

from .diff import (
    ChangeKind,
    DiffSegment,
    SectionChange,
    VersionDiff,
    changed_sections,
    diff_versions,
)
from .restore import RestoreResult, restore_version
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
    "ChangeKind",
    "ChangeType",
    "DiffSegment",
    "PayloadVersion",
    "PayloadVersionSummary",
    "RestoreResult",
    "SectionChange",
    "VersionDiff",
    "changed_sections",
    "create_version",
    "diff_versions",
    "ensure_initial_version",
    "get_current_version",
    "get_version",
    "list_versions",
    "restore_version",
]
