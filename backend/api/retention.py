"""Retention + right-to-deletion API — Phase 5 / Week 23 / Day 2.

  - ``POST /api/sessions/{id}/purge`` — firm_admin-only hard
    deletion. Requires explicit ``{"confirm": true}`` AND the
    session id echoed in ``{"typed_confirmation": "<session_id>"}``
    so a misclick can't trigger an unrecoverable purge.
  - ``GET /api/admin/firms/{id}/purges`` — read the firm's
    purge audit trail (deletion receipts).
  - ``PUT /api/admin/firms/{id}/retention`` — set the firm's
    retention window (firm_admin only).

The W23/D1 firm-scope guard is applied throughout: a Firm B
admin cannot purge a Firm A engagement or even discover that
its id exists.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.firm_scope import assert_firm_access, get_session_firm_id
from core.retention.deletion import (
    PurgeReport, list_purges_for_firm, purge_engagement,
)
from core.retention.policy import (
    get_firm_retention_days, set_firm_retention_days,
)

logger = logging.getLogger(__name__)

router = APIRouter()
session_router = APIRouter()


def _is_system_admin(user: dict) -> bool:
    return user.get("role") == "admin"


def _is_firm_admin(user: dict) -> bool:
    return user.get("default_firm_role") == "admin"


# ---------------------------------------------------------------------------
# POST /api/sessions/{id}/purge
# ---------------------------------------------------------------------------


class PurgeBody(BaseModel):
    """Two-step confirmation. ``confirm`` is the boolean flag;
    ``typed_confirmation`` must equal the session id being
    purged. A misclick survives both gates together."""

    confirm: bool = Field(...)
    typed_confirmation: str = Field(..., min_length=1, max_length=128)


@session_router.post("/{session_id}/purge")
async def purge_session(
    session_id: str,
    body: PurgeBody = Body(...),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Hard-delete an engagement + every associated record + every
    artifact file. Firm-admin only. Two-step confirmation required.
    """
    # Firm-admin gate (firm-scoped admin OR system admin).
    if not (_is_firm_admin(user) or _is_system_admin(user)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="firm_admin role required to purge engagements",
        )

    # Cross-firm guard FIRST — a firm-B admin asking for a firm-A
    # session must get 404, not 403 (anti-enumeration).
    sess_firm = await get_session_firm_id(session_id)
    await assert_firm_access(
        user=user,
        resource_firm_id=sess_firm,
        resource_kind="session",
        resource_id=session_id,
        # Even a system admin must confirm-then-purge per the
        # W23/D2 hard rule; system-admin allowance is for read
        # paths, not destructive ones.
        allow_system_admin=True,
    )

    # Two-step confirmation gate.
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="purge requires confirm=true",
        )
    if body.typed_confirmation.strip() != session_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "typed_confirmation must equal the session id "
                "being purged"
            ),
        )

    try:
        report: PurgeReport = await purge_engagement(
            session_id=session_id,
            actor_user_id=user.get("user_id"),
            purge_reason="firm_admin_request",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e),
        )
    return report.to_dict()


# ---------------------------------------------------------------------------
# GET /api/admin/firms/{id}/purges
# ---------------------------------------------------------------------------


@router.get("/firms/{firm_id}/purges")
async def list_firm_purges(
    firm_id: str,
    limit: int = 100,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Read the purge audit trail for one firm. Firm-admin for
    their own firm; system-admin for any."""
    if not (_is_system_admin(user) or _is_firm_admin(user)):
        raise HTTPException(status_code=403, detail="Admin role required")
    if (
        _is_firm_admin(user)
        and not _is_system_admin(user)
        and user.get("default_firm_id") != firm_id
    ):
        raise HTTPException(status_code=404, detail="Firm not found")
    rows = await list_purges_for_firm(firm_id, limit=int(limit))
    return {"firm_id": firm_id, "purges": rows}


# ---------------------------------------------------------------------------
# PUT /api/admin/firms/{id}/retention
# ---------------------------------------------------------------------------


class RetentionBody(BaseModel):
    """Per-firm retention policy. ``retention_days = None`` →
    keep indefinitely (the default)."""

    retention_days: int | None = Field(default=None)


@router.put("/firms/{firm_id}/retention")
async def set_retention(
    firm_id: str,
    body: RetentionBody = Body(...),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if not (_is_system_admin(user) or _is_firm_admin(user)):
        raise HTTPException(status_code=403, detail="Admin role required")
    if (
        _is_firm_admin(user)
        and not _is_system_admin(user)
        and user.get("default_firm_id") != firm_id
    ):
        raise HTTPException(status_code=404, detail="Firm not found")
    try:
        await set_firm_retention_days(firm_id, body.retention_days)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "firm_id": firm_id,
        "retention_days": await get_firm_retention_days(firm_id),
    }


__all__ = ["router", "session_router"]
