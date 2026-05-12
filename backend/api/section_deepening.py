"""Section-deepening API — Phase 2 / Week 9 / Day 1.

Three endpoints mounted under ``/api/sessions/{session_id}/deepen``:

  POST /                  -> kick off a deepening; returns ``deepening_id``
                             immediately, the service runs in the background.
  GET  /{deepening_id}    -> poll for status + result.
  GET  /                  -> list all deepenings for the session.

Permissions: read-tier on the session is required for both GET
endpoints; write-tier is required for POST (firing a deepening
consumes LLM budget).
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from auth.dependencies import get_current_user
from auth.permissions import can_read, can_write
from core.section_deepening import (
    DeepeningNotAcceptableError,
    DeepeningNotFoundError,
    DeepeningRequest,
    SectionNotFoundError,
    accept_deepening,
    deepen_section,
    reject_deepening,
)
from db.connection import acquire

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Permission helpers (mirror sessions.py pattern)
# ---------------------------------------------------------------------------


async def _require_read(session_id: str, user: dict) -> None:
    if not await can_read(session_id, user):
        raise HTTPException(status_code=404, detail="Session not found")


async def _require_write(session_id: str, user: dict) -> None:
    if not await can_write(session_id, user):
        raise HTTPException(status_code=403, detail="Write access required to deepen sections")


# ---------------------------------------------------------------------------
# Request/response shapes
# ---------------------------------------------------------------------------


from pydantic import BaseModel, Field


class DeepenSectionBody(BaseModel):
    section_path: str = Field(..., min_length=1, max_length=200)
    depth_directive: str | None = Field(None, max_length=4000)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# DB helpers — read-only access to section_deepening_runs
# ---------------------------------------------------------------------------


def _normalize_jsonb(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


async def _get_run(session_id: str, deepening_id: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, firm_id, section_path, depth_directive,
                   triggered_by, original_section_json, deepened_section_json,
                   new_evidence_chunks_used, new_claim_ids, cost_usd, wall_seconds,
                   status, failure_reason, created_at, completed_at,
                   accepted_at, accepted_by, rejected_at, rejected_by
            FROM section_deepening_runs
            WHERE id = $1::uuid AND session_id = $2::uuid
            """,
            deepening_id,
            session_id,
        )
    if not row:
        return None
    d = dict(row)
    d["original_section_json"] = _normalize_jsonb(d.get("original_section_json"))
    d["deepened_section_json"] = _normalize_jsonb(d.get("deepened_section_json"))
    d["new_claim_ids"] = _normalize_jsonb(d.get("new_claim_ids")) or []
    return d


async def _list_runs(session_id: str) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, section_path, depth_directive, status, failure_reason,
                   new_evidence_chunks_used, cost_usd, wall_seconds,
                   created_at, completed_at
            FROM section_deepening_runs
            WHERE session_id = $1::uuid
            ORDER BY created_at DESC
            """,
            session_id,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{session_id}/deepen")
async def deepen_endpoint(
    session_id: str,
    body: DeepenSectionBody,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Kick off a section-deepening run. Returns immediately with the
    ``deepening_id``; poll the GET endpoint for status."""
    await _require_write(session_id, user)
    try:
        request = DeepeningRequest(
            session_id=UUID(session_id),
            section_path=body.section_path,
            depth_directive=body.depth_directive,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid request: {e}") from e

    triggered_by = UUID(user["user_id"])

    # FastAPI BackgroundTasks runs after the response is sent.
    # ``deepen_section`` does its own persistence (creates the
    # queued row, transitions through running, finalises with
    # complete/failed) so the GET endpoint sees a row immediately
    # once the background task lands its first INSERT.
    background_tasks.add_task(_run_in_background, request, triggered_by)
    return {
        "status": "queued",
        "section_path": body.section_path,
        "depth_directive": body.depth_directive,
        "session_id": session_id,
    }


async def _run_in_background(request: DeepeningRequest, triggered_by: UUID) -> None:
    """Thin wrapper so background-task exceptions land in the log."""
    try:
        await deepen_section(request, triggered_by)
    except Exception:  # noqa: BLE001
        logger.exception(
            "section deepening background task crashed (session=%s, path=%s)",
            request.session_id,
            request.section_path,
        )


@router.get("/{session_id}/deepen/{deepening_id}")
async def get_deepening_endpoint(
    session_id: str,
    deepening_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Poll one deepening's status + result."""
    await _require_read(session_id, user)
    row = await _get_run(session_id, deepening_id)
    if not row:
        raise HTTPException(status_code=404, detail="deepening not found")
    return row


@router.get("/{session_id}/deepen")
async def list_deepenings_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List all deepenings for the session, newest first."""
    await _require_read(session_id, user)
    return await _list_runs(session_id)


# ---------------------------------------------------------------------------
# W9/D3 — accept + reject
# ---------------------------------------------------------------------------


@router.post("/{session_id}/deepen/{deepening_id}/accept")
async def accept_deepening_endpoint(
    session_id: str,
    deepening_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Accept a completed deepening: splice the deepened section
    into the live report payload, snapshot the pre-accept state on
    the deepening row, and write a ``section_deepening.accepted``
    audit event. Idempotent — a second accept is a no-op."""
    await _require_write(session_id, user)
    try:
        return await accept_deepening(
            UUID(session_id),
            UUID(deepening_id),
            UUID(user["user_id"]),
        )
    except DeepeningNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except DeepeningNotAcceptableError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SectionNotFoundError as e:
        raise HTTPException(
            status_code=409,
            detail=(
                "Section path no longer resolves against the current payload — "
                f"the memo drifted since this deepening was created: {e}"
            ),
        ) from e


@router.post("/{session_id}/deepen/{deepening_id}/reject")
async def reject_deepening_endpoint(
    session_id: str,
    deepening_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Reject a deepening: mark the row rejected + write a
    ``section_deepening.rejected`` audit event. Idempotent."""
    await _require_write(session_id, user)
    try:
        return await reject_deepening(
            UUID(session_id),
            UUID(deepening_id),
            UUID(user["user_id"]),
        )
    except DeepeningNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except DeepeningNotAcceptableError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
