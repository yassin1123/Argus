"""Notification inbox API — Phase 4 / Week 18 / Day 4.

Four endpoints, all self-only:

  GET   /api/me/notifications                  paginated feed
  GET   /api/me/notifications/unread-count     bell badge
  POST  /api/notifications/{id}/read           mark one read
  POST  /api/me/notifications/read-all         mark every unread read

Authorisation is implicit — the current user is the recipient
filter on every read; the per-id read endpoint additionally
verifies the row's ``recipient_id`` matches before flipping.

Pagination is cursor-style on ``created_at``: pass ``before`` as
the ISO timestamp of the oldest row in the previous page to fetch
the next slice. ``limit`` is capped at 100 to keep the round-trip
predictable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.dependencies import get_current_user
from core.notifications.dispatcher import Notification, mark_read
from db.connection import acquire

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_uid(user: dict) -> UUID:
    try:
        return UUID(str(user["user_id"]))
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid user_id: {e}") from e


async def _load_feed(
    recipient_id: UUID,
    *,
    unread_only: bool,
    limit: int,
    before: datetime | None,
) -> list[Notification]:
    where = ["recipient_id = $1::uuid"]
    args: list[Any] = [recipient_id]
    if unread_only:
        where.append("read = FALSE")
    if before is not None:
        args.append(before)
        where.append(f"created_at < ${len(args)}")
    args.append(int(limit))
    limit_pos = f"${len(args)}"

    sql = f"""
        SELECT id, recipient_id, firm_id, notification_type,
               session_id, source_ref, actor_id, summary,
               read, read_at, created_at, email_status
          FROM notifications
         WHERE {' AND '.join(where)}
         ORDER BY created_at DESC, id DESC
         LIMIT {limit_pos}
    """
    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [Notification.from_row(r) for r in rows]


async def _unread_count(recipient_id: UUID) -> int:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COUNT(*) AS n
              FROM notifications
             WHERE recipient_id = $1::uuid AND read = FALSE
            """,
            recipient_id,
        )
    return int(row["n"] or 0)


async def _mark_all_read(recipient_id: UUID) -> int:
    async with acquire() as conn:
        result = await conn.execute(
            """
            UPDATE notifications
               SET read = TRUE, read_at = NOW()
             WHERE recipient_id = $1::uuid AND read = FALSE
            """,
            recipient_id,
        )
    try:
        return int(result.split()[-1])
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/me/notifications")
async def list_notifications_endpoint(
    unread: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    before: str | None = Query(default=None, max_length=40),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Paginated feed. ``unread=true`` filters to unread only;
    ``before`` is the ISO timestamp of the oldest row in the
    previous page (cursor pagination)."""
    uid = _parse_uid(user)
    before_dt: datetime | None = None
    if before:
        try:
            before_dt = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"invalid before timestamp: {e}",
            ) from e
    notifs = await _load_feed(
        uid, unread_only=unread, limit=limit, before=before_dt,
    )
    return {
        "user_id": str(uid),
        "notifications": [n.to_dict() for n in notifs],
        "count": len(notifs),
        # next-page cursor: oldest row's created_at, or None if exhausted
        "next_before": notifs[-1].created_at if notifs and len(notifs) == limit else None,
    }


@router.get("/me/notifications/unread-count")
async def unread_count_endpoint(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Powers the bell badge. Cheap (one COUNT)."""
    uid = _parse_uid(user)
    return {"user_id": str(uid), "unread_count": await _unread_count(uid)}


@router.post("/notifications/{notification_id}/read")
async def mark_one_read_endpoint(
    notification_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark a single notification read. 404 when the row doesn't
    belong to the current user — the underlying helper's
    WHERE recipient_id = $2 guarantees no cross-user leakage."""
    uid = _parse_uid(user)
    try:
        nid = UUID(notification_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e
    flipped = await mark_read(nid, uid)
    if not flipped:
        # Either the row doesn't exist, isn't ours, or was already
        # read. We don't distinguish — anti-enumeration + same
        # response shape keeps the client simple.
        return {"id": notification_id, "read": True, "changed": False}
    return {"id": notification_id, "read": True, "changed": True}


@router.post("/me/notifications/read-all")
async def mark_all_read_endpoint(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    uid = _parse_uid(user)
    n = await _mark_all_read(uid)
    return {"user_id": str(uid), "marked_read": n}


__all__ = ["router"]
