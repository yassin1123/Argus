"""Users-scoped endpoints — Phase 4 / Week 16 / Day 4.

Single endpoint today: cross-engagement "my mentions" for the
workspace home dashboard. A user can query their own mentions; a
firm admin can query any member of their firm. Cross-firm reads
are not permitted under any role (W16/D4 hard rule).

Mounted at ``/api/users`` in :mod:`main`. Future user-scoped
endpoints (profile fetch, preference toggles) land here too.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.dependencies import get_current_user
from auth.firm_permissions import is_firm_admin
from core.comments.threads import list_mentions_for_user
from db.connection import acquire

logger = logging.getLogger(__name__)

router = APIRouter()


async def _load_user_firm(user_id: UUID) -> UUID | None:
    """Return the user's earliest firm_id — used to scope the
    mentions query so cross-firm rows are excluded even when a row
    accidentally references a user_id from another tenant. Returns
    None if the user has no firm membership."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT firm_id FROM firm_memberships
             WHERE user_id = $1::uuid
             ORDER BY created_at ASC
             LIMIT 1
            """,
            user_id,
        )
    return row["firm_id"] if row else None


@router.get("/{user_id}/mentions")
async def get_user_mentions_endpoint(
    user_id: str,
    unresolved_only: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Cross-engagement mentions for a user. Self-only unless the
    caller is a firm admin of the target user's firm. Cross-firm
    reads return 404 (anti-enumeration, matches the W5 pattern).
    """
    try:
        target = UUID(user_id)
        actor = UUID(user["user_id"])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e

    target_firm = await _load_user_firm(target)
    if target_firm is None:
        # The target either doesn't exist or isn't in any firm.
        # Don't leak that distinction.
        raise HTTPException(status_code=404, detail="User not found")

    if target != actor:
        # Cross-user read — gated to firm admins of the target's firm.
        # is_firm_admin already returns False on cross-firm so this
        # also rejects cross-firm callers.
        admin = await is_firm_admin(str(target_firm), user)
        if not admin:
            raise HTTPException(
                status_code=403,
                detail="You can only view your own mentions.",
            )

    rows = await list_mentions_for_user(
        target,
        firm_id=target_firm,
        unresolved_only=unresolved_only,
        limit=limit,
    )
    return {
        "user_id": user_id,
        "firm_id": str(target_firm),
        "mentions": rows,
        "total": len(rows),
    }


__all__ = ["router"]
