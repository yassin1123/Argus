"""Section ownership + work-status — Phase 4 / Week 17 / Day 2.

One assignment row per ``(session_id, section_path)`` — re-assigning
a section overwrites in place via UPSERT. The W9 ``get_section``
addressing layer validates that ``section_path`` actually exists in
the live consulting_payload before we persist anything (per W17/D2
hard rule "don't allow section assignment to a section_path that
doesn't exist in the payload").

Authorization gates:
  - Assign / re-assign / unassign: engagement lead OR firm admin.
  - Change status: the section's current owner OR engagement lead
    OR firm admin (a contributor cannot change a section they
    don't own — per W17/D2 hard rule).

Status enum is :class:`SectionStatus`; the canonical workflow
direction is NOT_STARTED → IN_PROGRESS → NEEDS_REVIEW → DONE but
backwards transitions are allowed (re-open a DONE section).

Audit: every mutation emits one of ``section.assigned``,
``section.status_changed``, ``section.unassigned``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from audit.queries import append_event
from db.connection import acquire

from core.section_deepening.addressing import (
    SectionNotFoundError,
    get_section,
)

from .membership import (
    _active_lead_id,
    _is_firm_admin,
    _load_active,
    _load_session_firm,
)
from .section_status import SectionStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class SectionAssignment:
    """Service-layer row shape."""

    id: str
    session_id: str
    firm_id: str
    section_path: str
    assigned_to: str | None
    assigned_by: str | None
    status: str
    assigned_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> "SectionAssignment":
        return cls(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            firm_id=str(row["firm_id"]),
            section_path=str(row["section_path"]),
            assigned_to=str(row["assigned_to"]) if row.get("assigned_to") else None,
            assigned_by=str(row["assigned_by"]) if row.get("assigned_by") else None,
            status=str(row["status"]),
            assigned_at=row["assigned_at"].isoformat() if row.get("assigned_at") else "",
            updated_at=row["updated_at"].isoformat() if row.get("updated_at") else "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "firm_id": self.firm_id,
            "section_path": self.section_path,
            "assigned_to": self.assigned_to,
            "assigned_by": self.assigned_by,
            "status": self.status,
            "assigned_at": self.assigned_at,
            "updated_at": self.updated_at,
        }


@dataclass
class AssignmentResult:
    """Uniform return shape for every mutator."""

    ok: bool
    assignment: SectionAssignment | None = None
    status_code: int = 200
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# Canonical error reasons — short + 4xx-body safe.
_AUTHOR_GATE = "engagement lead or firm admin only"
_OWNER_OR_LEAD_GATE = "section owner, engagement lead, or firm admin only"
_NOT_MEMBER = "assignee must already be an engagement member"
_BAD_PATH = "section_path does not resolve against the live payload"
_BAD_STATUS = "invalid section status"
_NOT_FOUND = "section assignment not found"
_SESSION_NOT_FOUND = "session not found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _can_manage(session_id: UUID, actor_id: UUID) -> bool:
    """Lead or firm-admin gate."""
    firm_id = await _load_session_firm(session_id)
    if firm_id is None:
        return False
    if await _is_firm_admin(firm_id, actor_id):
        return True
    lead = await _active_lead_id(session_id)
    return bool(lead) and str(lead) == str(actor_id)


async def _load_payload(session_id: UUID) -> dict[str, Any]:
    """Merged reports + consulting_payload shape — same projection
    the W16 orphan detector + comments service use."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT recommendation, confidence_level, summary, key_reasons, risks,
                   counterarguments, next_steps, sources, caveats, consulting_payload
              FROM reports WHERE session_id = $1::uuid
            """,
            session_id,
        )
    if not row:
        return {}
    out: dict[str, Any] = {}
    for k in row.keys():
        if k == "consulting_payload":
            continue
        v = row[k]
        if isinstance(v, str) and k in (
            "key_reasons", "risks", "counterarguments", "next_steps", "sources",
        ):
            try:
                v = json.loads(v)
                if isinstance(v, str):
                    try:
                        v_inner = json.loads(v)
                        if isinstance(v_inner, (list, dict)):
                            v = v_inner
                    except Exception:
                        pass
            except Exception:
                pass
        out[k] = v
    cp = row["consulting_payload"]
    if isinstance(cp, str):
        try:
            cp = json.loads(cp)
        except Exception:
            cp = {}
    if isinstance(cp, dict):
        out.update(cp)
    return out


async def _audit(
    *,
    action: str,
    actor_user_id: UUID,
    session_id: UUID,
    section_path: str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "session_id": str(session_id),
        "section_path": section_path,
    }
    if extra:
        payload.update(extra)
    await append_event(
        action=action,
        actor_user_id=str(actor_user_id),
        resource_type="section_assignment",
        resource_id=None,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def assign_section(
    session_id: UUID,
    section_path: str,
    assigned_to: UUID,
    assigned_by: UUID,
) -> AssignmentResult:
    """Assign ownership of a section to an engagement member.
    Validates four things up front:

      1. Session exists; actor can manage (lead OR firm admin).
      2. Assignee is currently an engagement member (active row).
      3. section_path resolves via :func:`get_section` against the
         live payload.
      4. UPSERT preserves existing status when re-assigning so an
         in_progress section doesn't reset to not_started.
    """
    if not section_path or not section_path.strip():
        return AssignmentResult(ok=False, status_code=400, reason=_BAD_PATH)

    firm_id = await _load_session_firm(session_id)
    if firm_id is None:
        return AssignmentResult(ok=False, status_code=404, reason=_SESSION_NOT_FOUND)
    if not await _can_manage(session_id, assigned_by):
        return AssignmentResult(ok=False, status_code=403, reason=_AUTHOR_GATE)

    # The assignee must already be on the engagement — we don't
    # auto-add to engagement_memberships here (that's an explicit
    # caller decision, surfaced cleanly so the UI can prompt
    # "Add Sarah as contributor first?").
    existing_member = await _load_active(session_id, assigned_to)
    if existing_member is None:
        return AssignmentResult(ok=False, status_code=400, reason=_NOT_MEMBER)

    # Validate section_path against the live payload.
    payload = await _load_payload(session_id)
    try:
        get_section(payload, section_path)
    except SectionNotFoundError as e:
        return AssignmentResult(
            ok=False, status_code=400,
            reason=f"{_BAD_PATH}: {str(e)[:200]}",
        )

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO section_assignments
                (session_id, firm_id, section_path, assigned_to, assigned_by)
            VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5::uuid)
            ON CONFLICT (session_id, section_path) DO UPDATE
              SET assigned_to = EXCLUDED.assigned_to,
                  assigned_by = EXCLUDED.assigned_by,
                  updated_at  = NOW()
            RETURNING id, session_id, firm_id, section_path,
                      assigned_to, assigned_by, status,
                      assigned_at, updated_at
            """,
            session_id, firm_id, section_path, assigned_to, assigned_by,
        )

    assignment = SectionAssignment.from_row(row)
    await _audit(
        action="section.assigned",
        actor_user_id=assigned_by,
        session_id=session_id,
        section_path=section_path,
        extra={"assigned_to": str(assigned_to), "status": assignment.status},
    )

    # W18/D2: notify the assignee (best-effort).
    from core.notifications.wiring import notify_section_assigned
    await notify_section_assigned(
        session_id=session_id, firm_id=firm_id, actor_id=assigned_by,
        section_path=section_path, assigned_user_id=assigned_to,
    )

    return AssignmentResult(ok=True, assignment=assignment)


async def set_section_status(
    session_id: UUID,
    section_path: str,
    status: str | SectionStatus,
    actor_id: UUID,
) -> AssignmentResult:
    """Change a section's status. The actor must be the section
    owner OR the engagement lead OR a firm admin (per W17/D2 hard
    rule — contributors cannot change sections they don't own)."""
    status_enum = (
        status if isinstance(status, SectionStatus)
        else _coerce_status(status)
    )
    if status_enum is None:
        return AssignmentResult(ok=False, status_code=400, reason=_BAD_STATUS)

    existing = await _load_assignment(session_id, section_path)
    if existing is None:
        return AssignmentResult(ok=False, status_code=404, reason=_NOT_FOUND)

    owner_id = existing.assigned_to
    is_owner = bool(owner_id) and str(owner_id) == str(actor_id)
    if not is_owner and not await _can_manage(session_id, actor_id):
        return AssignmentResult(ok=False, status_code=403, reason=_OWNER_OR_LEAD_GATE)

    old_status = existing.status
    if old_status == status_enum.value:
        return AssignmentResult(
            ok=True, assignment=existing, extra={"no_op": True},
        )

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE section_assignments
               SET status = $3, updated_at = NOW()
             WHERE session_id = $1::uuid AND section_path = $2
            RETURNING id, session_id, firm_id, section_path,
                      assigned_to, assigned_by, status,
                      assigned_at, updated_at
            """,
            session_id, section_path, status_enum.value,
        )

    assignment = SectionAssignment.from_row(row)
    await _audit(
        action="section.status_changed",
        actor_user_id=actor_id,
        session_id=session_id,
        section_path=section_path,
        extra={"old_status": old_status, "new_status": status_enum.value,
               "assigned_to": owner_id},
    )

    # W17/D2: surface needs_review as a distinct event so W18
    # notifications can listen. The audit row above already
    # captures the status change; this is the targeted hook.
    if status_enum is SectionStatus.NEEDS_REVIEW:
        await _audit(
            action="section.needs_review",
            actor_user_id=actor_id,
            session_id=session_id,
            section_path=section_path,
            extra={"assigned_to": owner_id},
        )
        # W18/D2: notify the engagement lead (best-effort). The
        # recipient resolver pulls the active lead; actor exclusion
        # kicks in if the lead IS the owner who flipped the status.
        from core.notifications.wiring import notify_section_needs_review
        await notify_section_needs_review(
            session_id=session_id,
            firm_id=UUID(str(existing.firm_id)) if not isinstance(existing.firm_id, UUID)
                    else existing.firm_id,
            actor_id=actor_id, section_path=section_path,
        )

    return AssignmentResult(ok=True, assignment=assignment)


async def unassign_section(
    session_id: UUID,
    section_path: str,
    actor_id: UUID,
) -> AssignmentResult:
    """Remove the owner from a section (status reverts to
    not_started). Lead / admin only."""
    if not await _can_manage(session_id, actor_id):
        return AssignmentResult(ok=False, status_code=403, reason=_AUTHOR_GATE)
    existing = await _load_assignment(session_id, section_path)
    if existing is None:
        return AssignmentResult(ok=False, status_code=404, reason=_NOT_FOUND)

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE section_assignments
               SET assigned_to = NULL,
                   status      = 'not_started',
                   updated_at  = NOW()
             WHERE session_id = $1::uuid AND section_path = $2
            RETURNING id, session_id, firm_id, section_path,
                      assigned_to, assigned_by, status,
                      assigned_at, updated_at
            """,
            session_id, section_path,
        )

    assignment = SectionAssignment.from_row(row)
    await _audit(
        action="section.unassigned",
        actor_user_id=actor_id,
        session_id=session_id,
        section_path=section_path,
        extra={"previous_assigned_to": existing.assigned_to,
               "previous_status": existing.status},
    )
    return AssignmentResult(ok=True, assignment=assignment)


async def list_section_assignments(
    session_id: UUID,
) -> list[SectionAssignment]:
    """Every assignment row for a session, ordered by section_path."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, firm_id, section_path,
                   assigned_to, assigned_by, status,
                   assigned_at, updated_at
              FROM section_assignments
             WHERE session_id = $1::uuid
             ORDER BY section_path ASC
            """,
            session_id,
        )
    return [SectionAssignment.from_row(r) for r in rows]


async def get_sections_owned_by(
    user_id: UUID, session_id: UUID | None = None,
) -> list[SectionAssignment]:
    """Sections owned by a user. When ``session_id`` is provided
    the result is scoped to one engagement; otherwise it's the
    cross-engagement view for the user's home dashboard (W17/D4)."""
    async with acquire() as conn:
        if session_id is None:
            rows = await conn.fetch(
                """
                SELECT id, session_id, firm_id, section_path,
                       assigned_to, assigned_by, status,
                       assigned_at, updated_at
                  FROM section_assignments
                 WHERE assigned_to = $1::uuid
                 ORDER BY updated_at DESC, section_path ASC
                """,
                user_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, session_id, firm_id, section_path,
                       assigned_to, assigned_by, status,
                       assigned_at, updated_at
                  FROM section_assignments
                 WHERE assigned_to = $1::uuid
                   AND session_id = $2::uuid
                 ORDER BY section_path ASC
                """,
                user_id, session_id,
            )
    return [SectionAssignment.from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


async def _load_assignment(
    session_id: UUID, section_path: str,
) -> SectionAssignment | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, firm_id, section_path,
                   assigned_to, assigned_by, status,
                   assigned_at, updated_at
              FROM section_assignments
             WHERE session_id = $1::uuid AND section_path = $2
            """,
            session_id, section_path,
        )
    return SectionAssignment.from_row(row) if row else None


def _coerce_status(value: str) -> SectionStatus | None:
    try:
        return SectionStatus(value)
    except ValueError:
        return None


__all__ = [
    "AssignmentResult",
    "SectionAssignment",
    "assign_section",
    "get_sections_owned_by",
    "list_section_assignments",
    "set_section_status",
    "unassign_section",
]
