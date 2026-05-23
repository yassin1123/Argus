"""Unified "my work" view — Phase 4 / Week 17 / Day 3.

Combines the derived task aggregator (:mod:`.tasks`) with the
explicit task service (:mod:`.explicit_tasks`) into a single
per-person picture. Default scope is cross-engagement so this
backs the user's home dashboard. Pass a ``session_id`` to scope
to one engagement (used by the workspace shell's "my work" tab).

Output shape:

  - ``tasks``: flat list of unified task entries, each tagged with
    ``source`` = ``"derived"`` | ``"explicit"`` so the UI can
    style differently.
  - ``by_engagement``: same tasks grouped by ``session_id`` with the
    engagement title denormalised — keeps the home dashboard's
    "Kestrel: 3 open" rollup cheap to render.
  - ``totals``: ``{high, medium, low}`` for the priority histogram.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from db.connection import acquire

from .explicit_tasks import ExplicitTask, list_open_tasks_for_user
from .tasks import DerivedTask, derive_tasks_for_user

logger = logging.getLogger(__name__)


@dataclass
class UnifiedTask:
    """Single shape covering both derived + explicit. The UI renders
    against this; callers don't need to branch by ``source``."""

    source: str  # "derived" | "explicit"
    task_type: str
    session_id: str
    section_path: str | None
    source_ref: str
    summary: str
    priority: str
    created_at: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "task_type": self.task_type,
            "session_id": self.session_id,
            "section_path": self.section_path,
            "source_ref": self.source_ref,
            "summary": self.summary,
            "priority": self.priority,
            "created_at": self.created_at,
            "extra": self.extra,
        }


@dataclass
class MyWork:
    user_id: str
    scope: str  # "all" or a session_id
    tasks: list[UnifiedTask] = field(default_factory=list)
    by_engagement: dict[str, dict[str, Any]] = field(default_factory=dict)
    totals: dict[str, int] = field(default_factory=lambda: {"high": 0, "medium": 0, "low": 0})

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "scope": self.scope,
            "tasks": [t.to_dict() for t in self.tasks],
            "by_engagement": self.by_engagement,
            "totals": self.totals,
        }


_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _derived_to_unified(t: DerivedTask) -> UnifiedTask:
    return UnifiedTask(
        source="derived",
        task_type=t.task_type,
        session_id=t.session_id,
        section_path=t.section_path,
        source_ref=t.source_ref,
        summary=t.summary,
        priority=t.priority,
        created_at=t.created_at,
        extra=t.extra,
    )


def _explicit_to_unified(t: ExplicitTask) -> UnifiedTask:
    # Explicit tasks default to medium priority — there's no
    # severity signal on the row. The W17/D3 hard rule keeps
    # explicit tasks intentionally simple.
    return UnifiedTask(
        source="explicit",
        task_type="explicit",
        session_id=t.session_id,
        section_path=t.section_path,
        source_ref=t.id,
        summary=t.title,
        priority="medium",
        created_at=t.created_at,
        extra={"created_by": t.created_by},
    )


async def _load_engagement_titles(session_ids: set[str]) -> dict[str, str]:
    if not session_ids:
        return {}
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title FROM sessions WHERE id = ANY($1::uuid[])",
            [UUID(s) for s in session_ids],
        )
    return {str(r["id"]): (r["title"] or "") for r in rows}


async def get_my_work(
    user_id: UUID, *, scope: str | UUID = "all",
) -> MyWork:
    """Build the unified my-work view.

    ``scope='all'`` (default) → cross-engagement.
    ``scope=<session_uuid>`` → engagement-scoped.

    Active-engagements bound is applied inside the derivation
    helpers, so a delivered engagement won't produce ghost work.
    """
    session_filter: UUID | None = None
    if isinstance(scope, UUID):
        session_filter = scope
        scope_label = str(scope)
    elif scope != "all":
        try:
            session_filter = UUID(scope)
            scope_label = scope
        except ValueError:
            scope_label = "all"
    else:
        scope_label = "all"

    derived = await derive_tasks_for_user(user_id, session_filter)
    explicit = await list_open_tasks_for_user(user_id, session_id=session_filter)

    tasks: list[UnifiedTask] = (
        [_derived_to_unified(d) for d in derived]
        + [_explicit_to_unified(e) for e in explicit]
    )
    # Sort by (priority asc, recency desc).
    tasks.sort(key=lambda t: (
        _PRIORITY_RANK.get(t.priority, 9),
        f"~{t.created_at}" if t.created_at else "~",
    ))

    # Engagement-title denormalisation for the home dashboard.
    session_ids = {t.session_id for t in tasks}
    titles = await _load_engagement_titles(session_ids)
    by_engagement: dict[str, dict[str, Any]] = {}
    for t in tasks:
        bucket = by_engagement.setdefault(t.session_id, {
            "session_id": t.session_id,
            "engagement_title": titles.get(t.session_id, ""),
            "tasks": [],
            "counts": {"high": 0, "medium": 0, "low": 0, "total": 0},
        })
        bucket["tasks"].append(t.to_dict())
        bucket["counts"][t.priority] = bucket["counts"].get(t.priority, 0) + 1
        bucket["counts"]["total"] += 1

    totals = {"high": 0, "medium": 0, "low": 0}
    for t in tasks:
        totals[t.priority] = totals.get(t.priority, 0) + 1

    return MyWork(
        user_id=str(user_id),
        scope=scope_label,
        tasks=tasks,
        by_engagement=by_engagement,
        totals=totals,
    )


__all__ = ["MyWork", "UnifiedTask", "get_my_work"]
