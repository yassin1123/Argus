"""Per-type recipient resolution — Phase 4 / Week 18 / Day 1.

Each notification type knows how to enumerate its recipients from
the event's ``context`` + a small set of DB lookups (engagement
lead, assigned reviewer, thread participants). The dispatcher
ALWAYS filters out ``event.actor_id`` after this returns — that
filter is the hard rule "don't notify the actor for their own
action".

Recipients are returned as a de-duplicated list of UUIDs in stable
insertion order so the dispatcher's downstream batch can pick the
highest-priority type deterministically.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from db.connection import acquire

from .types import NotificationType

if TYPE_CHECKING:
    from .dispatcher import NotificationEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _engagement_lead(session_id: UUID) -> UUID | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id FROM engagement_memberships
             WHERE engagement_id = $1::uuid
               AND role = 'lead'
               AND removed_at IS NULL
             LIMIT 1
            """,
            session_id,
        )
    return row["user_id"] if row else None


async def _session_columns(session_id: UUID) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT review_assigned_to, submitted_by, created_by_user_id
              FROM sessions WHERE id = $1::uuid
            """,
            session_id,
        )
    return dict(row) if row else None


async def _thread_participants(root_comment_id: UUID) -> list[UUID]:
    """Distinct authors who've posted in a thread (root + replies).
    Used by COMMENT_REPLY recipient resolution. Excludes soft-
    deleted rows."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT author_id
              FROM comments
             WHERE (id = $1::uuid OR parent_comment_id = $1::uuid)
               AND deleted_at IS NULL
            """,
            root_comment_id,
        )
    return [r["author_id"] for r in rows]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def resolve_recipients(event: "NotificationEvent") -> list[UUID]:
    """Return the recipient user_ids for an event. The dispatcher
    is responsible for actor exclusion + preference application;
    this function only knows the per-type business rule."""
    t = event.notification_type
    ctx = event.context or {}

    # ----- W16: mentions / replies -----
    if t is NotificationType.MENTION:
        ids = ctx.get("mentioned_user_ids") or []
        return _coerce_uuid_list(ids)

    if t is NotificationType.COMMENT_REPLY:
        # Recipients are everyone who's previously posted on the
        # thread (root + prior replies). The dispatcher filters the
        # actor out afterwards.
        root_id = ctx.get("root_comment_id")
        if not root_id:
            return []
        try:
            root_uuid = root_id if isinstance(root_id, UUID) else UUID(str(root_id))
        except (ValueError, TypeError):
            return []
        return await _thread_participants(root_uuid)

    # ----- W17: assignments / status -----
    if t in (
        NotificationType.ENGAGEMENT_ASSIGNED,
        NotificationType.SECTION_ASSIGNED,
        NotificationType.TASK_ASSIGNED,
    ):
        target = ctx.get("assigned_to") or ctx.get("target_user_id")
        return _coerce_uuid_list([target] if target else [])

    if t is NotificationType.SECTION_NEEDS_REVIEW:
        # Engagement lead — the spec's choice. (Could plausibly also
        # ping the reviewer; today we keep it tight to the lead so
        # we don't double-notify when the reviewer is also CC'd via
        # a separate REVIEW_REQUESTED event.)
        if event.session_id is None:
            return []
        lead = await _engagement_lead(event.session_id)
        return [lead] if lead else []

    # ----- W15: review workflow -----
    if t is NotificationType.REVIEW_REQUESTED:
        # The assigned reviewer for the engagement.
        if event.session_id is None:
            return []
        sess = await _session_columns(event.session_id)
        if not sess:
            return []
        reviewer = sess.get("review_assigned_to")
        return [reviewer] if reviewer else []

    if t in (NotificationType.CHANGES_REQUESTED, NotificationType.REVIEW_APPROVED):
        # The submitter (denormalised on sessions.submitted_by from
        # W15/D2) + the engagement lead. Both want to know.
        if event.session_id is None:
            return []
        sess = await _session_columns(event.session_id)
        if not sess:
            return []
        out: list[UUID] = []
        seen: set[str] = set()
        for col in ("submitted_by", "created_by_user_id"):
            uid = sess.get(col)
            if uid and str(uid) not in seen:
                out.append(uid)
                seen.add(str(uid))
        lead = await _engagement_lead(event.session_id)
        if lead and str(lead) not in seen:
            out.append(lead)
        return out

    # Unknown type — empty rather than guess.
    logger.debug("resolve_recipients: unknown type %r", t)
    return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_uuid_list(values: list[Any]) -> list[UUID]:
    out: list[UUID] = []
    seen: set[str] = set()
    for v in values or []:
        if v is None:
            continue
        try:
            uid = v if isinstance(v, UUID) else UUID(str(v))
        except (ValueError, TypeError):
            continue
        if str(uid) in seen:
            continue
        seen.add(str(uid))
        out.append(uid)
    return out


__all__ = ["resolve_recipients"]
