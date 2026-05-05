"""DB writes + reads for the audit log."""

from __future__ import annotations

import json
import logging
from typing import Any

from db.connection import acquire

logger = logging.getLogger(__name__)


async def append_event(
    *,
    action: str,
    actor_user_id: str | None,
    actor_email: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    method: str | None = None,
    path: str | None = None,
    status_code: int | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Best-effort append. Never raises — auditing must not break the request."""
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_events (actor_user_id, actor_email, action, resource_type,
                                          resource_id, method, path, status_code, ip, user_agent, payload)
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                """,
                actor_user_id,
                actor_email,
                action,
                resource_type,
                resource_id,
                method,
                path,
                status_code,
                ip,
                (user_agent or "")[:500],
                json.dumps(payload or {}),
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("audit append skipped: %s", e)


async def list_events_for_engagement(
    engagement_id: str, *, limit: int = 200
) -> list[dict[str, Any]]:
    """All audit rows that touched a given engagement (resource_type='engagement' OR
    payload mentions the engagement_id)."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, actor_user_id, actor_email, action, resource_type, resource_id,
                   method, path, status_code, ip, payload, created_at
            FROM audit_events
            WHERE (resource_type = 'engagement' AND resource_id = $1)
               OR payload->>'engagement_id' = $1
            ORDER BY id DESC
            LIMIT $2
            """,
            engagement_id,
            int(limit),
        )
    return [_row(r) for r in rows]


async def list_recent_events(*, limit: int = 200) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, actor_user_id, actor_email, action, resource_type, resource_id,
                   method, path, status_code, ip, payload, created_at
            FROM audit_events
            ORDER BY id DESC
            LIMIT $1
            """,
            int(limit),
        )
    return [_row(r) for r in rows]


def _row(r: Any) -> dict[str, Any]:
    pl = r["payload"]
    if isinstance(pl, str):
        try:
            pl = json.loads(pl)
        except Exception:
            pl = {}
    return {
        "id": int(r["id"]),
        "actor_user_id": str(r["actor_user_id"]) if r["actor_user_id"] else None,
        "actor_email": r["actor_email"],
        "action": r["action"],
        "resource_type": r["resource_type"],
        "resource_id": r["resource_id"],
        "method": r["method"],
        "path": r["path"],
        "status_code": r["status_code"],
        "ip": r["ip"],
        "payload": pl or {},
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }
