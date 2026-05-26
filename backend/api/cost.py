"""Cost API — Phase 5 / Week 20 / Day 3.

Three endpoints, role-gated:

  - ``GET /api/sessions/{id}/cost`` — engagement breakdown
    (any firm member of the engagement; cross-firm callers get
    a 404 to avoid existence-leak).
  - ``GET /api/admin/firms/{id}/cost?from=&to=`` — firm rollup.
    Firm-admin for their own firm; system-admin for any.
  - ``GET /api/admin/cost/by-model?from=&to=`` — system-wide.
    System-admin only.

Auth resolution shared with W20/D2 metrics: firm-admin is
``user.default_firm_role == 'admin'`` and is forced to their own
firm. System-admin is ``user.role == 'admin'``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.dependencies import get_current_user
from core.observability.cost_rollups import (
    cost_by_model,
    engagement_cost,
    firm_cost,
)
from db.connection import acquire


router = APIRouter()


def _is_system_admin(user: dict) -> bool:
    return user.get("role") == "admin"


def _is_firm_admin(user: dict) -> bool:
    return user.get("default_firm_role") == "admin"


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"invalid ISO timestamp: {s!r}",
        )


# ---------------------------------------------------------------------------
# Per-engagement
# ---------------------------------------------------------------------------


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


async def _user_can_read_session(session_id: str, user: dict) -> bool:
    """The caller can read the cost of a session iff they're a
    member of the firm that owns it (or a system-admin). Anything
    else returns 404 in the route handler — we do NOT distinguish
    "not your firm" from "not found" to avoid existence-leak.
    """
    if _is_system_admin(user):
        return True
    sess_firm = await _session_firm_id(session_id)
    if sess_firm is None:
        return False
    return user.get("default_firm_id") == sess_firm


# Mounted under /api/sessions (no /api/admin prefix) so members
# without admin role can still see their engagement's cost panel.
session_router = APIRouter()


@session_router.get("/{session_id}/cost")
async def get_engagement_cost(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Cost breakdown for a single engagement."""
    if not await _user_can_read_session(session_id, user):
        # Existence-leak guard: 404 not 403.
        raise HTTPException(status_code=404, detail="Session not found")
    result = await engagement_cost(session_id)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Per-firm
# ---------------------------------------------------------------------------


@router.get("/firms/{firm_id}/cost")
async def get_firm_cost(
    firm_id: str,
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Windowed firm-level cost rollup. Firm-admin must be reading
    their own firm; system-admin can read any."""
    if not (_is_system_admin(user) or _is_firm_admin(user)):
        raise HTTPException(
            status_code=403, detail="Admin role required",
        )
    # Firm-admin cannot read another firm's cost — same leak-
    # prevention rule as the W20/D2 metrics endpoint.
    if (
        _is_firm_admin(user)
        and not _is_system_admin(user)
        and user.get("default_firm_id") != firm_id
    ):
        raise HTTPException(status_code=404, detail="Firm not found")

    f = _parse_iso(from_ts)
    t = _parse_iso(to_ts)
    if f is None and t is None:
        t = datetime.now(tz=timezone.utc)
        f = t - timedelta(days=30)
    result = await firm_cost(firm_id, from_ts=f, to_ts=t)
    return result.to_dict()


# ---------------------------------------------------------------------------
# System-wide by-model
# ---------------------------------------------------------------------------


@router.get("/cost/by-model")
async def get_cost_by_model(
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """System-wide model cost distribution. System-admin only —
    explicitly NOT exposed to firm-admins (would aggregate across
    firms and leak provider/model mix between them)."""
    if not _is_system_admin(user):
        raise HTTPException(
            status_code=403, detail="System admin required",
        )
    f = _parse_iso(from_ts)
    t = _parse_iso(to_ts)
    if f is None and t is None:
        t = datetime.now(tz=timezone.utc)
        f = t - timedelta(days=30)
    rows = await cost_by_model(from_ts=f, to_ts=t)
    return {
        "from": f.isoformat() if f else None,
        "to": t.isoformat() if t else None,
        "rows": rows,
    }


__all__ = ["router", "session_router"]
