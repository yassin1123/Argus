"""Section coverage map — Phase 4 / Week 17 / Day 2.

The "is everything covered?" view for an engagement lead. For each
trackable section in the live payload, list:

  - whether an assignment row exists
  - the current owner + status (if assigned)
  - "unassigned" surface for sections with no owner

Plus a derived ``ready_to_submit`` advisory flag — True when every
trackable section is ``done``. This is the W17/D2 hook that the
workspace UI uses to render "all sections complete — ready to
submit for review" next to the W15 submit button. The flag is
ADVISORY only per W17/D2 hard rule "Don't auto-submit when all
sections are done; the lead decides."

The trackable-section enumeration comes from two sources:

  1. :const:`section_status.TRACKABLE_SECTION_PATHS` — the canonical
     set (mirrors the frontend W9 DEEPENABLE_PATHS).
  2. The live payload's actual top-level keys + frameworks subkeys.

Intersection of the two is what shows in the coverage map. So a
growth-mode engagement won't show ghost M&A-only sections, and an
M&A engagement won't show growth-only sections.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from .section_assignments import (
    SectionAssignment,
    _load_payload,
    list_section_assignments,
)
from .section_status import SectionStatus, TRACKABLE_SECTION_PATHS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class CoverageEntry:
    """Per-section row in the coverage map."""

    section_path: str
    assigned: bool
    assigned_to: str | None = None
    assigned_by: str | None = None
    status: str = SectionStatus.NOT_STARTED.value
    assignment_id: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_path": self.section_path,
            "assigned": self.assigned,
            "assigned_to": self.assigned_to,
            "assigned_by": self.assigned_by,
            "status": self.status,
            "assignment_id": self.assignment_id,
            "updated_at": self.updated_at,
        }


@dataclass
class CoverageMap:
    """The full coverage view returned by :func:`section_coverage`."""

    session_id: str
    entries: list[CoverageEntry] = field(default_factory=list)
    unassigned_count: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    ready_to_submit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "entries": [e.to_dict() for e in self.entries],
            "unassigned_count": self.unassigned_count,
            "by_status": self.by_status,
            "ready_to_submit": self.ready_to_submit,
        }


# ---------------------------------------------------------------------------
# Payload section enumeration
# ---------------------------------------------------------------------------


def _enumerate_payload_sections(payload: dict[str, Any]) -> set[str]:
    """Pull the section_paths actually present in this engagement's
    payload. We walk the top-level keys + the frameworks subkeys
    (the only nested namespace W9 surfaces). Anything outside
    :const:`TRACKABLE_SECTION_PATHS` is filtered downstream."""
    paths: set[str] = set()
    if not isinstance(payload, dict):
        return paths
    for k, v in payload.items():
        paths.add(k)
        if k == "frameworks" and isinstance(v, dict):
            for sub_k, sub_v in v.items():
                if sub_v is None:
                    continue
                paths.add(f"frameworks.{sub_k}")
    return paths


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def section_coverage(session_id: UUID) -> CoverageMap:
    """Build the coverage map for an engagement. Per-section entry
    includes assignment + status; the top-level summary surfaces the
    unassigned count + a status histogram + the advisory
    ``ready_to_submit`` flag."""
    payload = await _load_payload(session_id)
    payload_paths = _enumerate_payload_sections(payload)
    trackable = payload_paths & TRACKABLE_SECTION_PATHS
    # Sort deterministically — keeps the workspace UI's section
    # order stable across reloads.
    ordered_paths = sorted(trackable)

    assignments = await list_section_assignments(session_id)
    by_path: dict[str, SectionAssignment] = {
        a.section_path: a for a in assignments
    }

    entries: list[CoverageEntry] = []
    unassigned_count = 0
    by_status: dict[str, int] = {s.value: 0 for s in SectionStatus}

    for path in ordered_paths:
        a = by_path.get(path)
        if a is None or not a.assigned_to:
            entries.append(CoverageEntry(
                section_path=path,
                assigned=False,
                status=SectionStatus.NOT_STARTED.value,
            ))
            unassigned_count += 1
            by_status[SectionStatus.NOT_STARTED.value] += 1
            continue
        entries.append(CoverageEntry(
            section_path=path,
            assigned=True,
            assigned_to=a.assigned_to,
            assigned_by=a.assigned_by,
            status=a.status,
            assignment_id=a.id,
            updated_at=a.updated_at,
        ))
        by_status[a.status] = by_status.get(a.status, 0) + 1

    # Surface any assignment rows for sections we DIDN'T list — that
    # happens when the payload changed shape (e.g. a section was
    # renamed via section deepening) but the assignment row outlived
    # the rename. Show these so the lead can clean them up.
    leftover = [a for a in assignments if a.section_path not in trackable]
    for a in leftover:
        entries.append(CoverageEntry(
            section_path=a.section_path,
            assigned=bool(a.assigned_to),
            assigned_to=a.assigned_to,
            assigned_by=a.assigned_by,
            status=a.status,
            assignment_id=a.id,
            updated_at=a.updated_at,
        ))
        if a.assigned_to is None:
            unassigned_count += 1
        by_status[a.status] = by_status.get(a.status, 0) + 1

    # ``ready_to_submit`` — true only when every TRACKABLE entry is
    # done AND nothing is unassigned. Leftover rows from removed
    # sections are tolerated (they're a UI cleanup task, not a gate).
    ready = (
        len(ordered_paths) > 0
        and unassigned_count == 0
        and all(
            e.status == SectionStatus.DONE.value
            for e in entries
            if e.section_path in trackable
        )
    )

    return CoverageMap(
        session_id=str(session_id),
        entries=entries,
        unassigned_count=unassigned_count,
        by_status=by_status,
        ready_to_submit=ready,
    )


__all__ = ["CoverageEntry", "CoverageMap", "section_coverage"]
