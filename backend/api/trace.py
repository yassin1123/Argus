"""Trace API — Phase 5 / Week 20 / Day 4.

  - ``GET /api/sessions/{id}/trace`` — assembled lifecycle trace.
    Firm members of the engagement's firm + system-admin can read.
    Anyone else gets 404 (existence-leak guard).
  - ``GET /api/admin/traces/recent?status=failed&hours=24`` — recent
    engagement digests. Firm-scoped for firm-admins; cross-firm
    for system-admins.

Same auth shape as the W20/D2 metrics + W20/D3 cost APIs.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.dependencies import get_current_user
from core.observability.trace_view import assemble_trace, recent_traces
from db.connection import acquire

router = APIRouter()
session_router = APIRouter()


def _is_system_admin(user: dict) -> bool:
    return user.get("role") == "admin"


def _is_firm_admin(user: dict) -> bool:
    return user.get("default_firm_role") == "admin"


async def _session_firm_id(session_id: str) -> str | None:
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT firm_id FROM sessions WHERE id = $1::uuid",
                session_id,
            )
        return str(row["firm_id"]) if row and row["firm_id"] else None
    except Exception:  # noqa: BLE001
        return None


@session_router.get("/{session_id}/trace")
async def get_engagement_trace(
    session_id: str,
    run_id: str | None = Query(
        None, description="optional run_id filter (W20/D1 trace context)",
    ),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Assembled lifecycle trace for one engagement. Firm members
    of the engagement's firm + system-admin can read. Otherwise
    404 (we don't distinguish "not your firm" from "doesn't exist"
    — existence-leak guard, same shape as the W20/D3 cost endpoint).
    """
    sess_firm = await _session_firm_id(session_id)
    if sess_firm is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if not _is_system_admin(user) and user.get("default_firm_id") != sess_firm:
        raise HTTPException(status_code=404, detail="Session not found")
    trace = await assemble_trace(session_id, run_id=run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return trace.to_dict()


@router.get("/traces/recent")
async def get_recent_traces(
    status: str | None = Query(
        None, description="filter by status, e.g. 'failed' or 'complete'",
    ),
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(50, ge=1, le=200),
    firm_id: str | None = Query(
        None, description="(system-admin only) restrict to one firm",
    ),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Recent-engagement digest for debugging. Firm-admins are
    forced to their own firm regardless of any ``?firm_id`` they
    pass — same cross-firm leak guard as the W20/D2 metrics API."""
    if not (_is_system_admin(user) or _is_firm_admin(user)):
        raise HTTPException(status_code=403, detail="Admin role required")
    if _is_system_admin(user):
        scoped_firm = firm_id
    else:
        scoped_firm = user.get("default_firm_id")
    rows = await recent_traces(
        status=status, firm_id=scoped_firm,
        hours=int(hours), limit=int(limit),
    )
    return {
        "status_filter": status,
        "hours": int(hours),
        "firm_scoped_to": scoped_firm,
        "traces": rows,
    }


__all__ = ["router", "session_router"]
