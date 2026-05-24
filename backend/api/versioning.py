"""Payload version history API — Phase 4 / Week 19 / Day 2.

Four endpoints, all firm-scoped (cross-firm callers see 404,
matching the W15+ pattern):

  GET    /api/sessions/{id}/versions            list (metadata)
  GET    /api/sessions/{id}/versions/{n}        full snapshot
  GET    /api/sessions/{id}/versions/diff       ?a=&b= diff
  POST   /api/sessions/{id}/versions/{n}/restore  restore
                                                   ({confirm_revert})
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.permissions import can_read
from core.versioning import (
    diff_versions,
    get_version,
    list_versions,
    restore_version,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Bodies
# ---------------------------------------------------------------------------


class RestoreBody(BaseModel):
    """Restore on an approved/delivered engagement requires the
    explicit ``confirm_revert`` flag — without it the service
    returns 409 with a clean reason. Matches W15's "editing costs
    the approval" posture."""

    confirm_revert: bool = Field(default=False)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_read(session_id: str, user: dict) -> None:
    if not await can_read(session_id, user):
        raise HTTPException(status_code=404, detail="Session not found")


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid {label}: {e}") from e


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/sessions/{session_id}/versions")
async def list_versions_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Metadata-only feed, newest first. NO ``payload_snapshot``
    bytes per W19/D1 hard rule."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    rows = await list_versions(sid)
    return {
        "session_id": session_id,
        "versions": [r.to_dict() for r in rows],
        "total": len(rows),
    }


@router.get("/sessions/{session_id}/versions/diff")
async def diff_versions_endpoint(
    session_id: str,
    a: int = Query(..., ge=1, description="Older version_number"),
    b: int = Query(..., ge=1, description="Newer version_number"),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Per-section change list (added | removed | modified) +
    word-level diff for each modified section + claim_changes
    (added / removed claim_ids)."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    diff = await diff_versions(sid, int(a), int(b))
    if diff is None:
        raise HTTPException(status_code=404, detail="version not found")
    return diff.to_dict()


@router.get("/sessions/{session_id}/versions/{version_number}")
async def get_version_endpoint(
    session_id: str,
    version_number: int,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Full snapshot for one specific version. Used by the W19/D3
    history reader when the user clicks a row to inspect."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    v = await get_version(sid, int(version_number))
    if v is None:
        raise HTTPException(status_code=404, detail="version not found")
    return v.to_dict()


@router.post("/sessions/{session_id}/versions/{version_number}/restore")
async def restore_version_endpoint(
    session_id: str,
    version_number: int,
    body: RestoreBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Restore a prior version. Append-only — creates a new
    ``change_type=restore`` version. Returns 409 when the
    engagement is approved/delivered and ``confirm_revert=false``;
    returns 403 for non-lead/non-author non-admin; returns 409 if
    a deepening is in flight."""
    await _require_read(session_id, user)
    sid = _parse_uuid(session_id, "session id")
    actor = _parse_uuid(user["user_id"], "user_id")

    result = await restore_version(
        sid, int(version_number), actor,
        confirm_revert=body.confirm_revert,
    )
    if not result.ok:
        raise HTTPException(
            status_code=result.status_code,
            detail={
                "reason": result.reason,
                **(result.extra or {}),
            } if result.extra else result.reason,
        )
    return result.to_dict()


__all__ = ["router"]
