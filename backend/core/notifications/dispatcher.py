"""Notification dispatcher — Phase 4 / Week 18 / Day 1.

  - ``dispatch(event)``: persists one type's notifications for the
    resolved recipient set (minus the actor).
  - ``dispatch_batch(events)``: same pipeline applied across
    multiple typed events with cross-event dedup — when a recipient
    qualifies via multiple events that share the SAME
    ``source_key`` (session_id + canonical source_ref hash), only
    the highest-priority type's notification is created. Used by
    Day 2's wiring when a single comment posts both a MENTION
    (for the @-tagged user) AND a COMMENT_REPLY (for the thread
    participants) and the @-tagged user happens to be one of the
    participants.

Hard rules (W18/D1):

  - Actor exclusion is unconditional. A user is never notified for
    their own action.
  - One notification per (recipient, source_key) per dispatch call.
    Cross-event collapse keeps the highest-priority type.
  - ``email_status`` is set on row creation: ``pending`` if the
    user's preference enables email; ``skipped`` if not. Day 3
    flips ``pending`` → ``sent`` / ``failed``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from db.connection import acquire

from .defaults import default_preference
from .recipients import resolve_recipients
from .summaries import render_summary
from .types import NotificationType, priority_of

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class NotificationEvent:
    """Request shape for the dispatcher. ``context`` is the open-
    ended bag carried through to recipient resolution + summary
    rendering — per-type fields the dispatcher would otherwise have
    to fetch."""

    notification_type: NotificationType
    session_id: UUID | None
    firm_id: UUID
    actor_id: UUID
    source_ref: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class Notification:
    """Persisted shape, mirrors the ``notifications`` table."""

    id: str
    recipient_id: str
    firm_id: str
    notification_type: str
    session_id: str | None
    source_ref: dict[str, Any]
    actor_id: str | None
    summary: str
    read: bool
    read_at: str | None
    created_at: str
    email_status: str

    @classmethod
    def from_row(cls, row: Any) -> "Notification":
        sr = row["source_ref"]
        if isinstance(sr, str):
            try:
                sr = json.loads(sr)
            except Exception:
                sr = {}
        return cls(
            id=str(row["id"]),
            recipient_id=str(row["recipient_id"]),
            firm_id=str(row["firm_id"]),
            notification_type=str(row["notification_type"]),
            session_id=str(row["session_id"]) if row.get("session_id") else None,
            source_ref=sr or {},
            actor_id=str(row["actor_id"]) if row.get("actor_id") else None,
            summary=str(row["summary"]),
            read=bool(row["read"]),
            read_at=row["read_at"].isoformat() if row.get("read_at") else None,
            created_at=row["created_at"].isoformat(),
            email_status=str(row["email_status"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "recipient_id": self.recipient_id,
            "firm_id": self.firm_id,
            "notification_type": self.notification_type,
            "session_id": self.session_id,
            "source_ref": self.source_ref,
            "actor_id": self.actor_id,
            "summary": self.summary,
            "read": self.read,
            "read_at": self.read_at,
            "created_at": self.created_at,
            "email_status": self.email_status,
        }


# ---------------------------------------------------------------------------
# Preference + actor lookup
# ---------------------------------------------------------------------------


async def _user_preference(
    user_id: UUID, notification_type: NotificationType,
) -> tuple[bool, bool]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT in_app, email
              FROM notification_preferences
             WHERE user_id = $1::uuid AND notification_type = $2
            """,
            user_id, notification_type.value,
        )
    if row is None:
        return default_preference(notification_type)
    return bool(row["in_app"]), bool(row["email"])


async def _actor_display_name(actor_id: UUID | None) -> str:
    if actor_id is None:
        return "Someone"
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT full_name, email FROM users WHERE id = $1::uuid", actor_id,
        )
    if not row:
        return "Someone"
    return str(row["full_name"]) or str(row["email"]) or "Someone"


# ---------------------------------------------------------------------------
# Dispatch — single event
# ---------------------------------------------------------------------------


def _source_key(source_ref: dict[str, Any]) -> str:
    """Canonical hash key for cross-event dedup. Sorted JSON so the
    same dict in two orderings produces the same key."""
    try:
        return json.dumps(source_ref or {}, sort_keys=True, default=str)
    except Exception:
        return ""


async def _persist_one(
    event: NotificationEvent,
    recipient_id: UUID,
    actor_name: str,
) -> Notification | None:
    """Apply preferences, render the summary, INSERT a row. Returns
    None when the user has BOTH in_app and email disabled (we don't
    write a row no-one will see)."""
    in_app, email = await _user_preference(recipient_id, event.notification_type)
    if not in_app and not email:
        return None
    if not in_app:
        # Email-only is a future affordance; today we always need an
        # in_app row to drive the inbox + carry the email_status.
        # If the user opted in_app off, we still persist (so audit /
        # email path stays consistent) — they just won't see it in
        # the inbox UI when in_app=false is honored at read time.
        pass

    email_status = "pending" if email else "skipped"
    summary = render_summary(
        event.notification_type, actor_name, event.context or {},
    )
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO notifications
                (recipient_id, firm_id, notification_type, session_id,
                 source_ref, actor_id, summary, email_status)
            VALUES ($1::uuid, $2::uuid, $3, $4::uuid,
                    $5::jsonb, $6::uuid, $7, $8)
            RETURNING id, recipient_id, firm_id, notification_type,
                      session_id, source_ref, actor_id, summary,
                      read, read_at, created_at, email_status
            """,
            recipient_id,
            event.firm_id,
            event.notification_type.value,
            event.session_id,
            json.dumps(event.source_ref or {}),
            event.actor_id,
            summary,
            email_status,
        )
    return Notification.from_row(row)


async def dispatch(event: NotificationEvent) -> list[Notification]:
    """Single-event dispatch. Resolves recipients, excludes the
    actor, applies preferences, and persists one notification per
    surviving recipient. No cross-event dedup — that's
    :func:`dispatch_batch`'s job."""
    if not isinstance(event.notification_type, NotificationType):
        event.notification_type = NotificationType(event.notification_type)

    recipients = await resolve_recipients(event)
    actor = event.actor_id
    filtered = [r for r in recipients if str(r) != str(actor)]
    # Per-event dedup (the resolver might return the same id twice
    # in pathological cases; keep insertion order).
    seen: set[str] = set()
    deduped: list[UUID] = []
    for r in filtered:
        k = str(r)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(r)

    if not deduped:
        return []

    actor_name = await _actor_display_name(actor)
    out: list[Notification] = []
    for r in deduped:
        n = await _persist_one(event, r, actor_name)
        if n is not None:
            out.append(n)
    return out


# ---------------------------------------------------------------------------
# Dispatch — batched, cross-event dedup
# ---------------------------------------------------------------------------


async def dispatch_batch(
    events: list[NotificationEvent],
) -> list[Notification]:
    """Process multiple typed events with cross-event dedup. When
    the same ``(recipient, session_id, source_key)`` tuple
    qualifies via multiple events, only the highest-priority
    event's notification is persisted.

    The classic case: a single comment that mentions a thread
    participant. The caller dispatches BOTH a MENTION event and a
    COMMENT_REPLY event; the mentioned-participant gets one
    notification (MENTION wins on priority).

    Single-recipient events (e.g. SECTION_ASSIGNED) work fine here
    too — they just don't collide with anything else on the same
    source_key.
    """
    if not events:
        return []

    # Normalise + resolve recipients per event.
    per_event: list[tuple[NotificationEvent, list[UUID]]] = []
    for event in events:
        if not isinstance(event.notification_type, NotificationType):
            event.notification_type = NotificationType(event.notification_type)
        recips = await resolve_recipients(event)
        recips = [r for r in recips if str(r) != str(event.actor_id)]
        per_event.append((event, recips))

    # Pick winning (event, recipient) by priority within a
    # (recipient, session_id, source_key) bucket.
    winners: dict[tuple[str, str, str], tuple[NotificationEvent, UUID]] = {}
    for event, recips in per_event:
        src_key = _source_key(event.source_ref)
        sid_key = str(event.session_id) if event.session_id else ""
        for r in recips:
            key = (str(r), sid_key, src_key)
            existing = winners.get(key)
            if (existing is None
                    or priority_of(event.notification_type)
                       > priority_of(existing[0].notification_type)):
                winners[key] = (event, r)

    if not winners:
        return []

    # Cache actor display names — events typically share an actor.
    actor_name_cache: dict[str, str] = {}

    async def _name_for(actor_id: UUID | None) -> str:
        k = str(actor_id) if actor_id else ""
        if k in actor_name_cache:
            return actor_name_cache[k]
        n = await _actor_display_name(actor_id)
        actor_name_cache[k] = n
        return n

    out: list[Notification] = []
    for (event, recipient) in winners.values():
        actor_name = await _name_for(event.actor_id)
        n = await _persist_one(event, recipient, actor_name)
        if n is not None:
            out.append(n)
    return out


# ---------------------------------------------------------------------------
# Read helpers (used by Day 4's inbox API)
# ---------------------------------------------------------------------------


async def mark_read(notification_id: UUID, recipient_id: UUID) -> bool:
    """Mark a notification read. Returns True if the row was
    actually flipped (False on no-op / wrong recipient)."""
    async with acquire() as conn:
        result = await conn.execute(
            """
            UPDATE notifications
               SET read = TRUE, read_at = NOW()
             WHERE id = $1::uuid
               AND recipient_id = $2::uuid
               AND read = FALSE
            """,
            notification_id, recipient_id,
        )
    # asyncpg returns 'UPDATE N' — split to int.
    try:
        return int(result.split()[-1]) > 0
    except Exception:
        return False


__all__ = [
    "Notification",
    "NotificationEvent",
    "dispatch",
    "dispatch_batch",
    "mark_read",
]
