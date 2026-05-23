"""Derived task aggregation — Phase 4 / Week 17 / Day 3.

Derives a per-user task picture by joining four signals that already
exist on the platform:

  1. **section_incomplete** (W17/D2) — sections owned by the user
     whose status is not yet ``done``.
  2. **change_request** (W15/D3) — open change-request section
     pointers on sections owned by the user.
  3. **mention** (W16/D2) — unresolved comment threads where the
     user is @-mentioned (root OR any reply).
  4. **comment_on_owned_section** (W16+W17/D2) — unresolved comment
     threads anchored to a section the user owns, where the user
     isn't the author. (Author-of-own-comment isn't a task.)

Dedup rule: each ``(session_id, section_path)`` carries at most one
mention-flavored task — if a section the user owns has a mention,
it's counted as a ``mention`` (medium priority), not as both a
mention AND a comment_on_owned_section. Same path with multiple
unresolved threads collapses to one task with a ``count`` extra.

Priority heuristic:

  - change_request severity=blocking | major  → **high**
  - change_request severity=minor              → **medium**
  - mention                                     → **medium**
  - section_incomplete                          → **medium**
  - comment_on_owned_section                    → **low**

Scoping: an active-engagements bound (the W17/D3 hard rule) is the
join's WHERE clause — we filter to sessions whose ``review_state``
isn't ``delivered`` and whose ``deleted_at`` is NULL. Delivered or
deleted engagements don't generate work.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from db.connection import acquire

logger = logging.getLogger(__name__)


TaskType = Literal[
    "section_incomplete",
    "change_request",
    "mention",
    "comment_on_owned_section",
]
Priority = Literal["high", "medium", "low"]


@dataclass
class DerivedTask:
    task_type: TaskType
    session_id: str
    section_path: str | None
    source_ref: str  # comment_id, review_record_id, or section_assignment_id
    summary: str
    priority: Priority
    created_at: str  # ISO-format
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "session_id": self.session_id,
            "section_path": self.section_path,
            "source_ref": self.source_ref,
            "summary": self.summary,
            "priority": self.priority,
            "created_at": self.created_at,
            "extra": self.extra,
        }


_PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


def _sort_key(t: DerivedTask) -> tuple[int, str]:
    """Priority first (high→low), then newest first within a tier."""
    return (_PRIORITY_RANK.get(t.priority, 9), _negate_iso(t.created_at))


def _negate_iso(iso: str) -> str:
    """Trick to sort timestamps descending without parsing — ISO-8601
    strings sort lexicographically, and prepending a negation marker
    inverts the order. Cheap + correct for the timeframes we deal in."""
    # Use a tilde (~ has high ASCII value) so newer dates sort first.
    return f"~{iso}" if iso else "~"


# ---------------------------------------------------------------------------
# Per-signal derivation
# ---------------------------------------------------------------------------


async def _section_incomplete_tasks(
    user_id: UUID, session_id: UUID | None,
) -> list[DerivedTask]:
    sql = """
        SELECT sa.id, sa.session_id, sa.section_path, sa.status,
               sa.updated_at, sa.assigned_at, s.title
          FROM section_assignments sa
          JOIN sessions s ON s.id = sa.session_id
         WHERE sa.assigned_to = $1::uuid
           AND sa.status <> 'done'
           AND COALESCE(s.review_state, 'draft') <> 'delivered'
    """
    args: list[Any] = [user_id]
    if session_id is not None:
        sql += " AND sa.session_id = $2::uuid"
        args.append(session_id)
    sql += " ORDER BY sa.updated_at DESC"

    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [
        DerivedTask(
            task_type="section_incomplete",
            session_id=str(r["session_id"]),
            section_path=str(r["section_path"]),
            source_ref=str(r["id"]),
            summary=f"Finish section: {r['section_path']} (status: {r['status']})",
            priority="medium",
            created_at=(r["assigned_at"]).isoformat(),
            extra={"current_status": str(r["status"]),
                   "engagement_title": r["title"] or ""},
        )
        for r in rows
    ]


async def _change_request_tasks(
    user_id: UUID, session_id: UUID | None,
) -> list[DerivedTask]:
    """W15/D3 change-request pointers on sections owned by the user.
    Walks review_records.feedback (JSONB) for pointers whose
    section_path matches an owned section, where resolved=false."""
    sql = """
        SELECT rr.id AS review_record_id, rr.session_id, rr.feedback,
               rr.created_at, s.title, sa.id AS section_assignment_id,
               sa.section_path AS owned_section_path
          FROM review_records rr
          JOIN sessions s ON s.id = rr.session_id
          JOIN section_assignments sa
            ON sa.session_id = rr.session_id
           AND sa.assigned_to = $1::uuid
         WHERE rr.action = 'request_changes'
           AND COALESCE(s.review_state, 'draft') <> 'delivered'
    """
    args: list[Any] = [user_id]
    if session_id is not None:
        sql += " AND rr.session_id = $2::uuid"
        args.append(session_id)

    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)

    out: list[DerivedTask] = []
    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        fb = r["feedback"]
        if isinstance(fb, str):
            try:
                fb = json.loads(fb)
            except Exception:
                fb = {}
        if not isinstance(fb, dict):
            continue
        pointers = fb.get("section_pointers") or []
        if not isinstance(pointers, list):
            continue
        owned_path = str(r["owned_section_path"])
        for p in pointers:
            if not isinstance(p, dict):
                continue
            if p.get("resolved"):
                continue
            if p.get("section_path") != owned_path:
                continue
            key = (str(r["review_record_id"]), owned_path, str(r["session_id"]))
            if key in seen:
                continue
            seen.add(key)
            severity = str(p.get("severity") or "major")
            priority: Priority = (
                "high" if severity in ("blocking", "major") else "medium"
            )
            note_preview = str(p.get("note") or "")[:120]
            out.append(DerivedTask(
                task_type="change_request",
                session_id=str(r["session_id"]),
                section_path=owned_path,
                source_ref=str(r["review_record_id"]),
                summary=(
                    f"Address change request on {owned_path} ({severity})"
                    + (f" — {note_preview}" if note_preview else "")
                ),
                priority=priority,
                created_at=r["created_at"].isoformat(),
                extra={"severity": severity,
                       "section_assignment_id": str(r["section_assignment_id"]),
                       "engagement_title": r["title"] or ""},
            ))
    return out


async def _mention_tasks(
    user_id: UUID, session_id: UUID | None,
) -> list[DerivedTask]:
    """Unresolved comment threads where the user is @-mentioned in
    the root OR any reply. Uses the W16/D4 JSONB containment query
    (backed by the GIN index)."""
    sql = """
        SELECT c.id, c.session_id, c.parent_comment_id, c.anchor_type,
               c.anchor_ref, c.body, c.created_at,
               s.title
          FROM comments c
          JOIN sessions s ON s.id = c.session_id
         WHERE c.deleted_at IS NULL
           AND c.mentioned_user_ids @> $1::jsonb
           AND COALESCE(s.review_state, 'draft') <> 'delivered'
    """
    args: list[Any] = [json.dumps([str(user_id)])]
    if session_id is not None:
        sql += " AND c.session_id = $2::uuid"
        args.append(session_id)

    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)

    # Resolve mentions to their thread roots and filter to unresolved
    # threads. Pull root rows in one extra query.
    root_ids: set[str] = set()
    by_root: dict[str, dict[str, Any]] = {}
    rows_by_root: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        pid = r["parent_comment_id"]
        if pid:
            root_ids.add(str(pid))
            rows_by_root.setdefault(str(pid), []).append(dict(r))
        else:
            by_root[str(r["id"])] = dict(r)
            rows_by_root.setdefault(str(r["id"]), []).append(dict(r))

    # Fetch any root we haven't loaded yet (mentions inside replies).
    missing = [rid for rid in root_ids if rid not in by_root]
    if missing:
        async with acquire() as conn:
            fetched = await conn.fetch(
                """
                SELECT c.id, c.session_id, c.anchor_type, c.anchor_ref,
                       c.body, c.created_at, c.resolved, c.deleted_at, c.author_id,
                       s.title
                  FROM comments c
                  JOIN sessions s ON s.id = c.session_id
                 WHERE c.id = ANY($1::uuid[])
                """,
                [UUID(m) for m in missing],
            )
        for r in fetched:
            by_root[str(r["id"])] = dict(r)

    out: list[DerivedTask] = []
    seen_roots: set[str] = set()
    for root_id, root in by_root.items():
        # Skip roots that are deleted or already resolved.
        if root.get("deleted_at") is not None:
            continue
        if root.get("resolved"):
            # The mention can still be relevant if it's in an
            # unresolved REPLY, but if the root is closed the whole
            # thread is treated as done.
            continue
        if root_id in seen_roots:
            continue
        seen_roots.add(root_id)
        anchor_ref = root.get("anchor_ref")
        if isinstance(anchor_ref, str):
            try:
                anchor_ref = json.loads(anchor_ref)
            except Exception:
                anchor_ref = {}
        section_path = None
        if isinstance(anchor_ref, dict):
            section_path = anchor_ref.get("section_path")
        body_preview = str(root.get("body") or "")[:120]
        out.append(DerivedTask(
            task_type="mention",
            session_id=str(root["session_id"]),
            section_path=section_path,
            source_ref=root_id,
            summary=(
                f"You were @-mentioned: {body_preview}"
                if body_preview else "You were @-mentioned"
            ),
            priority="medium",
            created_at=root["created_at"].isoformat(),
            extra={"anchor_type": str(root.get("anchor_type") or ""),
                   "engagement_title": root.get("title") or ""},
        ))
    return out


async def _comment_on_owned_section_tasks(
    user_id: UUID, session_id: UUID | None,
) -> list[DerivedTask]:
    """Unresolved comment threads anchored to a section the user
    owns. Excludes threads the user authored themselves (commenting
    on your own work isn't a task)."""
    sql = """
        SELECT c.id, c.session_id, c.anchor_ref, c.body, c.created_at,
               c.author_id, s.title
          FROM comments c
          JOIN sessions s ON s.id = c.session_id
          JOIN section_assignments sa
            ON sa.session_id = c.session_id
           AND sa.assigned_to = $1::uuid
           AND sa.section_path = (c.anchor_ref ->> 'section_path')
         WHERE c.deleted_at IS NULL
           AND c.parent_comment_id IS NULL
           AND c.resolved = FALSE
           AND c.anchor_type IN ('section', 'text_range')
           AND c.author_id <> $1::uuid
           AND COALESCE(s.review_state, 'draft') <> 'delivered'
    """
    args: list[Any] = [user_id]
    if session_id is not None:
        sql += " AND c.session_id = $2::uuid"
        args.append(session_id)

    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)

    out: list[DerivedTask] = []
    for r in rows:
        anchor_ref = r["anchor_ref"]
        if isinstance(anchor_ref, str):
            try:
                anchor_ref = json.loads(anchor_ref)
            except Exception:
                anchor_ref = {}
        section_path = (anchor_ref or {}).get("section_path")
        body_preview = str(r["body"] or "")[:120]
        out.append(DerivedTask(
            task_type="comment_on_owned_section",
            session_id=str(r["session_id"]),
            section_path=section_path,
            source_ref=str(r["id"]),
            summary=(
                f"Unresolved comment on your section {section_path}: {body_preview}"
                if section_path else f"Unresolved comment: {body_preview}"
            ),
            priority="low",
            created_at=r["created_at"].isoformat(),
            extra={"engagement_title": r["title"] or ""},
        ))
    return out


# ---------------------------------------------------------------------------
# Dedup + public API
# ---------------------------------------------------------------------------


def _dedup(tasks: list[DerivedTask]) -> list[DerivedTask]:
    """Apply the W17/D3 dedup rules:

      - A ``mention`` whose source_ref matches a
        ``comment_on_owned_section`` source_ref keeps the mention
        (higher priority) and drops the comment-on-owned variant.
    """
    by_source: dict[str, list[DerivedTask]] = {}
    for t in tasks:
        by_source.setdefault(t.source_ref, []).append(t)

    kept: list[DerivedTask] = []
    for source_ref, group in by_source.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        # Prefer mention > comment_on_owned_section > others.
        priority_order = {
            "change_request": 0,
            "mention": 1,
            "comment_on_owned_section": 2,
            "section_incomplete": 3,
        }
        chosen = min(group, key=lambda t: priority_order.get(t.task_type, 9))
        kept.append(chosen)
    return kept


async def derive_tasks_for_user(
    user_id: UUID,
    session_id: UUID | None = None,
) -> list[DerivedTask]:
    """Aggregate every derived task for ``user_id``. When
    ``session_id`` is provided the result is scoped to that
    engagement; otherwise cross-engagement (filtered to active
    engagements per the W17/D3 hard rule).

    Sorted by (priority asc, recency desc) so the highest-priority
    newest task comes first.
    """
    section_tasks = await _section_incomplete_tasks(user_id, session_id)
    change_tasks = await _change_request_tasks(user_id, session_id)
    mention_tasks = await _mention_tasks(user_id, session_id)
    comment_tasks = await _comment_on_owned_section_tasks(user_id, session_id)

    combined = section_tasks + change_tasks + mention_tasks + comment_tasks
    combined = _dedup(combined)
    combined.sort(key=_sort_key)
    return combined


__all__ = ["DerivedTask", "derive_tasks_for_user"]
