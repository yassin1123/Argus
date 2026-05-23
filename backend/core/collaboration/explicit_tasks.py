"""Explicit (lightweight) engagement tasks — Phase 4 / Week 17 / Day 3.

Companion to the derived-task aggregator in :mod:`.tasks`. Most
tasks in Argus are derived from existing signals; this module backs
the small ad-hoc to-do surface ("ping the client lawyer") for items
that don't fit those rails.

Authorisation:

  - Create — any active engagement member.
  - Complete — the assignee OR the creator OR engagement lead OR
    firm admin. Anyone else gets 403.
  - List — any engagement member with read access (the API layer
    enforces this; the service doesn't gate beyond authoring).

Per the W17/D3 hard rule "don't build a full PM system", there are
no subtasks, no dependencies, no due dates. Just title + assignee
+ done. Reopening a done task isn't supported in v1 — create a
fresh task instead (matches the consultant workflow).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from audit.queries import append_event
from db.connection import acquire

from .membership import _active_lead_id, _is_firm_admin, _load_active, _load_session_firm

logger = logging.getLogger(__name__)


@dataclass
class ExplicitTask:
    id: str
    session_id: str
    firm_id: str
    title: str
    assigned_to: str | None
    created_by: str
    section_path: str | None
    done: bool
    done_at: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> "ExplicitTask":
        return cls(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            firm_id=str(row["firm_id"]),
            title=str(row["title"]),
            assigned_to=str(row["assigned_to"]) if row.get("assigned_to") else None,
            created_by=str(row["created_by"]),
            section_path=row.get("section_path"),
            done=bool(row["done"]),
            done_at=row["done_at"].isoformat() if row.get("done_at") else None,
            created_at=row["created_at"].isoformat(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "firm_id": self.firm_id,
            "title": self.title,
            "assigned_to": self.assigned_to,
            "created_by": self.created_by,
            "section_path": self.section_path,
            "done": self.done,
            "done_at": self.done_at,
            "created_at": self.created_at,
        }


@dataclass
class TaskResult:
    ok: bool
    task: ExplicitTask | None = None
    status_code: int = 200
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_TITLE_EMPTY = "task title cannot be empty"
_NOT_MEMBER = "only engagement members can create tasks"
_COMPLETE_GATE = "only the assignee, creator, lead, or firm admin can complete a task"
_NOT_FOUND = "task not found"
_SESSION_NOT_FOUND = "session not found"


async def _audit(
    *,
    action: str,
    actor_user_id: UUID,
    task_id: str | None,
    session_id: UUID,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {"session_id": str(session_id)}
    if extra:
        payload.update(extra)
    await append_event(
        action=action,
        actor_user_id=str(actor_user_id),
        resource_type="engagement_task",
        resource_id=task_id,
        payload=payload,
    )


async def create_task(
    session_id: UUID,
    title: str,
    created_by: UUID,
    *,
    assigned_to: UUID | None = None,
    section_path: str | None = None,
) -> TaskResult:
    """Create an explicit task on an engagement. Creator must be an
    active engagement member; assignee (when supplied) must be too."""
    if not title or not title.strip():
        return TaskResult(ok=False, status_code=400, reason=_TITLE_EMPTY)

    firm_id = await _load_session_firm(session_id)
    if firm_id is None:
        return TaskResult(ok=False, status_code=404, reason=_SESSION_NOT_FOUND)

    if not await _load_active(session_id, created_by):
        # Firm admin still allowed to create on any engagement in their firm.
        if not await _is_firm_admin(firm_id, created_by):
            return TaskResult(ok=False, status_code=403, reason=_NOT_MEMBER)

    if assigned_to is not None:
        if not await _load_active(session_id, assigned_to):
            return TaskResult(
                ok=False, status_code=400,
                reason="assignee must already be an engagement member",
            )

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO engagement_tasks
                (session_id, firm_id, title, assigned_to, created_by, section_path)
            VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5::uuid, $6)
            RETURNING id, session_id, firm_id, title, assigned_to,
                      created_by, section_path, done, done_at, created_at
            """,
            session_id, firm_id, title.strip(), assigned_to, created_by, section_path,
        )

    task = ExplicitTask.from_row(row)
    await _audit(
        action="task.created",
        actor_user_id=created_by,
        task_id=task.id,
        session_id=session_id,
        extra={"title": task.title, "assigned_to": task.assigned_to,
               "section_path": task.section_path},
    )
    return TaskResult(ok=True, task=task)


async def complete_task(task_id: UUID, actor_id: UUID) -> TaskResult:
    """Mark a task done. Assignee OR creator OR lead OR firm admin
    can complete; anyone else gets 403."""
    async with acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT id, session_id, firm_id, title, assigned_to,
                   created_by, section_path, done, done_at, created_at
              FROM engagement_tasks
             WHERE id = $1::uuid
            """,
            task_id,
        )
    if existing is None:
        return TaskResult(ok=False, status_code=404, reason=_NOT_FOUND)
    if existing["done"]:
        return TaskResult(ok=True, task=ExplicitTask.from_row(existing),
                          extra={"no_op": True})

    sid = UUID(str(existing["session_id"]))
    is_assignee = bool(existing["assigned_to"]) and str(existing["assigned_to"]) == str(actor_id)
    is_creator = str(existing["created_by"]) == str(actor_id)
    if not (is_assignee or is_creator):
        # Lead or firm admin fallback.
        firm_id = UUID(str(existing["firm_id"]))
        lead = await _active_lead_id(sid)
        is_lead = bool(lead) and str(lead) == str(actor_id)
        is_admin = await _is_firm_admin(firm_id, actor_id)
        if not (is_lead or is_admin):
            return TaskResult(ok=False, status_code=403, reason=_COMPLETE_GATE)

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE engagement_tasks
               SET done = TRUE, done_at = NOW()
             WHERE id = $1::uuid
            RETURNING id, session_id, firm_id, title, assigned_to,
                      created_by, section_path, done, done_at, created_at
            """,
            task_id,
        )
    task = ExplicitTask.from_row(row)
    await _audit(
        action="task.completed",
        actor_user_id=actor_id,
        task_id=task.id,
        session_id=sid,
    )
    return TaskResult(ok=True, task=task)


async def list_tasks_for_session(
    session_id: UUID, *, include_done: bool = True,
) -> list[ExplicitTask]:
    sql = """
        SELECT id, session_id, firm_id, title, assigned_to,
               created_by, section_path, done, done_at, created_at
          FROM engagement_tasks
         WHERE session_id = $1::uuid
    """
    if not include_done:
        sql += " AND done = FALSE"
    sql += " ORDER BY done ASC, created_at DESC"
    async with acquire() as conn:
        rows = await conn.fetch(sql, session_id)
    return [ExplicitTask.from_row(r) for r in rows]


async def list_open_tasks_for_user(
    user_id: UUID, *, session_id: UUID | None = None,
) -> list[ExplicitTask]:
    """Open explicit tasks assigned to a user. Used by
    :func:`my_work.get_my_work` for the cross-engagement view."""
    sql = """
        SELECT t.id, t.session_id, t.firm_id, t.title, t.assigned_to,
               t.created_by, t.section_path, t.done, t.done_at, t.created_at
          FROM engagement_tasks t
          JOIN sessions s ON s.id = t.session_id
         WHERE t.assigned_to = $1::uuid
           AND t.done = FALSE
           AND COALESCE(s.review_state, 'draft') <> 'delivered'
    """
    args: list[Any] = [user_id]
    if session_id is not None:
        sql += " AND t.session_id = $2::uuid"
        args.append(session_id)
    sql += " ORDER BY t.created_at DESC"
    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [ExplicitTask.from_row(r) for r in rows]


__all__ = [
    "ExplicitTask",
    "TaskResult",
    "complete_task",
    "create_task",
    "list_open_tasks_for_user",
    "list_tasks_for_session",
]
