"""Collaboration API — Phase 4 / Week 17 / Day 3.

Five endpoints exposing the W17/D3 surface:

  GET    /api/me/work                  — current user, cross-engagement
  GET    /api/sessions/{id}/work       — engagement-scoped (self by default;
                                          lead/admin can pass ?user_id=)
  POST   /api/sessions/{id}/tasks      — create explicit task
  POST   /api/tasks/{id}/complete      — complete explicit task
  GET    /api/sessions/{id}/tasks      — list explicit tasks

Routing strategy: this router declares its own per-endpoint
prefixes (``/me/work``, ``/sessions/...``, ``/tasks/...``) so it
mounts at ``/api`` rather than a single sub-tree. Same pattern the
W16/D2 comments router uses.

Authorisation:

  - ``/api/me/work``: always the current user — no cross-user query
    parameter accepted on this endpoint per W17/D3 hard rule
    "Don't let a user see another user's work unless they're the
    lead or admin." The lead/admin path goes through
    ``/api/sessions/{id}/work?user_id=``.
  - ``/api/sessions/{id}/work``: self by default; passing
    ``user_id`` requires the caller to be engagement lead OR firm
    admin (otherwise 403, even if the target is on the engagement).
  - Task create / list: any firm member with engagement read.
  - Task complete: gated by the service (assignee / creator / lead
    / firm admin).
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.permissions import can_read
from core.collaboration.coverage import section_coverage
from core.collaboration.explicit_tasks import (
    complete_task,
    create_task,
    list_tasks_for_session,
)
from core.collaboration.membership import (
    _active_lead_id,
    _is_firm_admin,
    _load_session_firm,
    assign_member,
    change_member_role,
    list_members,
    remove_member,
)
from core.collaboration.my_work import get_my_work
from core.collaboration.section_assignments import (
    assign_section,
    list_section_assignments,
    set_section_status,
    unassign_section,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateTaskBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    assigned_to: str | None = Field(default=None, max_length=36)
    section_path: str | None = Field(default=None, max_length=200)

    model_config = {"extra": "ignore"}


class AssignMemberBody(BaseModel):
    """W17/D1 surface — used by both POST (assign) and PATCH (change
    role). Re-using one body shape keeps the API symmetrical."""

    user_id: str = Field(..., max_length=36)
    role: str = Field(..., min_length=1, max_length=32)

    model_config = {"extra": "ignore"}


class ChangeRoleBody(BaseModel):
    role: str = Field(..., min_length=1, max_length=32)

    model_config = {"extra": "ignore"}


class AssignSectionBody(BaseModel):
    section_path: str = Field(..., min_length=1, max_length=200)
    assigned_to: str = Field(..., max_length=36)

    model_config = {"extra": "ignore"}


class SectionStatusBody(BaseModel):
    status: str = Field(..., min_length=1, max_length=32)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_read(session_id: str, user: dict) -> None:
    if not await can_read(session_id, user):
        raise HTTPException(status_code=404, detail="Session not found")


async def _is_lead_or_admin(session_id: UUID, actor_id: UUID) -> bool:
    firm_id = await _load_session_firm(session_id)
    if firm_id is None:
        return False
    if await _is_firm_admin(firm_id, actor_id):
        return True
    lead = await _active_lead_id(session_id)
    return bool(lead) and str(lead) == str(actor_id)


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid {label}: {e}") from e


# ---------------------------------------------------------------------------
# /api/me/work — cross-engagement, self only
# ---------------------------------------------------------------------------


@router.get("/me/work")
async def my_work_endpoint(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Unified cross-engagement my-work view for the current user.
    Always self — there's no ``?user_id=`` knob on this endpoint
    (use ``/api/sessions/{id}/work?user_id=`` for lead/admin
    queries)."""
    uid = _parse_uuid(user["user_id"], "user_id")
    work = await get_my_work(uid, scope="all")
    return work.to_dict()


# ---------------------------------------------------------------------------
# /api/sessions/{id}/work — engagement-scoped, lead/admin can target others
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/work")
async def session_work_endpoint(
    session_id: str,
    user_id: str | None = Query(default=None, max_length=36),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Engagement-scoped my-work. When ``user_id`` is omitted, the
    caller's own work is returned. When supplied, the caller must
    be engagement lead OR firm admin — anyone else gets 403."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    actor = _parse_uuid(user["user_id"], "user_id")

    target_id = actor
    if user_id is not None:
        target_id = _parse_uuid(user_id, "user_id")
        if target_id != actor:
            if not await _is_lead_or_admin(sid, actor):
                raise HTTPException(
                    status_code=403,
                    detail="You can only view your own work unless "
                            "you're the engagement lead or firm admin.",
                )

    work = await get_my_work(target_id, scope=sid)
    return work.to_dict()


# ---------------------------------------------------------------------------
# Explicit tasks — create / complete / list
# ---------------------------------------------------------------------------


@router.post("/sessions/{session_id}/tasks", status_code=201)
async def create_task_endpoint(
    session_id: str,
    body: CreateTaskBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Create an explicit task on an engagement. Creator must be an
    active engagement member (or firm admin); assignee — when
    supplied — must be an engagement member too."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    actor = _parse_uuid(user["user_id"], "user_id")
    assignee = _parse_uuid(body.assigned_to, "assigned_to") if body.assigned_to else None

    result = await create_task(
        session_id=sid, title=body.title, created_by=actor,
        assigned_to=assignee, section_path=body.section_path,
    )
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)
    assert result.task is not None
    return result.task.to_dict()


@router.post("/tasks/{task_id}/complete")
async def complete_task_endpoint(
    task_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark a task complete. Service-layer auth (assignee / creator
    / lead / firm admin)."""
    tid = _parse_uuid(task_id, "task id")
    actor = _parse_uuid(user["user_id"], "user_id")
    result = await complete_task(tid, actor)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)
    assert result.task is not None
    return result.task.to_dict()


@router.get("/sessions/{session_id}/tasks")
async def list_tasks_endpoint(
    session_id: str,
    include_done: bool = Query(default=True),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    tasks = await list_tasks_for_session(sid, include_done=include_done)
    return {
        "session_id": session_id,
        "tasks": [t.to_dict() for t in tasks],
        "total": len(tasks),
    }


# ---------------------------------------------------------------------------
# W17/D1 — engagement membership (member CRUD via W17 service)
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/members")
async def list_engagement_members_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Active members for an engagement (W17 vocabulary). Ordered
    lead-first."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    members = await list_members(sid)
    return {
        "session_id": session_id,
        "members": [m.to_dict() for m in members],
        "total": len(members),
    }


@router.post("/sessions/{session_id}/members", status_code=201)
async def assign_engagement_member_endpoint(
    session_id: str,
    body: AssignMemberBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Add a member to an engagement. Service enforces the W17/D1
    invariants — one lead, must be a firm member, etc."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    actor = _parse_uuid(user["user_id"], "user_id")
    target = _parse_uuid(body.user_id, "user_id")

    result = await assign_member(
        session_id=sid, user_id=target, role=body.role, assigned_by=actor,
    )
    if not result.ok:
        raise HTTPException(
            status_code=result.status_code,
            detail={"reason": result.reason, **result.extra}
                if result.extra else result.reason,
        )
    assert result.member is not None
    return result.member.to_dict()


@router.patch("/sessions/{session_id}/members/{user_id}")
async def change_engagement_member_role_endpoint(
    session_id: str,
    user_id: str,
    body: ChangeRoleBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Change a member's role. Service enforces lead-uniqueness +
    "can't demote the only lead" + reviewer-alignment with W15."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    actor = _parse_uuid(user["user_id"], "user_id")
    target = _parse_uuid(user_id, "user_id")

    result = await change_member_role(
        session_id=sid, user_id=target, new_role=body.role, actor_id=actor,
    )
    if not result.ok:
        raise HTTPException(
            status_code=result.status_code,
            detail={"reason": result.reason, **result.extra}
                if result.extra else result.reason,
        )
    assert result.member is not None
    return result.member.to_dict()


@router.delete("/sessions/{session_id}/members/{user_id}")
async def remove_engagement_member_endpoint(
    session_id: str,
    user_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Soft-remove a member. Rejects lead removal without a
    replacement lead (409)."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    actor = _parse_uuid(user["user_id"], "user_id")
    target = _parse_uuid(user_id, "user_id")

    result = await remove_member(session_id=sid, user_id=target, actor_id=actor)
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)
    return {"ok": True}


# ---------------------------------------------------------------------------
# W17/D2 — section ownership + work status
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/sections/coverage")
async def section_coverage_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Coverage map: every trackable section in the live payload with
    owner + status. Powers the W17/D4 CoverageIndicator + section
    ownership overlay."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    cov = await section_coverage(sid)
    return cov.to_dict()


@router.get("/sessions/{session_id}/sections/assignments")
async def list_section_assignments_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    rows = await list_section_assignments(sid)
    return {
        "session_id": session_id,
        "assignments": [r.to_dict() for r in rows],
        "total": len(rows),
    }


@router.post("/sessions/{session_id}/sections/assign", status_code=201)
async def assign_section_endpoint(
    session_id: str,
    body: AssignSectionBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Assign (or re-assign) a section to a member. Lead/admin only;
    service validates section_path + assignee is engagement member."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    actor = _parse_uuid(user["user_id"], "user_id")
    assignee = _parse_uuid(body.assigned_to, "assigned_to")

    result = await assign_section(
        session_id=sid, section_path=body.section_path,
        assigned_to=assignee, assigned_by=actor,
    )
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)
    assert result.assignment is not None
    return result.assignment.to_dict()


@router.patch("/sessions/{session_id}/sections/{section_path:path}/status")
async def set_section_status_endpoint(
    session_id: str,
    section_path: str,
    body: SectionStatusBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Change a section's work status. Owner / lead / firm admin only
    per W17/D2."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    actor = _parse_uuid(user["user_id"], "user_id")

    result = await set_section_status(
        session_id=sid, section_path=section_path,
        status=body.status, actor_id=actor,
    )
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)
    assert result.assignment is not None
    return result.assignment.to_dict()


@router.delete("/sessions/{session_id}/sections/{section_path:path}")
async def unassign_section_endpoint(
    session_id: str,
    section_path: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Remove the owner from a section. Lead/admin only."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    actor = _parse_uuid(user["user_id"], "user_id")

    result = await unassign_section(
        session_id=sid, section_path=section_path, actor_id=actor,
    )
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)
    assert result.assignment is not None
    return result.assignment.to_dict()


__all__ = ["router"]
