"""Session export artifacts API — W10/D2.

Mounted under ``/api/sessions`` so the routes shape as:

  POST /api/sessions/{session_id}/exports              -> kick off a render
  GET  /api/sessions/{session_id}/exports/{id}         -> status + metadata
  GET  /api/sessions/{session_id}/exports/{id}/download -> stream file
  GET  /api/sessions/{session_id}/exports              -> list

The legacy ``backend/api/exports.py`` router is separate — it serves a
different (older) deliverable shape under ``/api/exports``. Phase 5
collapses these into one surface; until then they coexist.

Permissions: firm-member read/write parity with the section-deepening
router (non-members get 404; read-only members get 403 on POST).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.permissions import can_read, can_write
from core.exports import (
    GenerateArtifactRequest,
    generate_artifact,
    get_artifact,
    list_artifacts,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Permission helpers
# ---------------------------------------------------------------------------


async def _require_read(session_id: str, user: dict) -> None:
    if not await can_read(session_id, user):
        raise HTTPException(status_code=404, detail="Session not found")


async def _require_write(session_id: str, user: dict) -> None:
    if not await can_read(session_id, user):
        raise HTTPException(status_code=404, detail="Session not found")
    if not await can_write(session_id, user):
        raise HTTPException(
            status_code=403, detail="Write access required to generate exports"
        )


# ---------------------------------------------------------------------------
# Request shapes
# ---------------------------------------------------------------------------


class GenerateExportBody(BaseModel):
    artifact_type: str = Field(..., min_length=1, max_length=40)
    format: str = Field(..., min_length=1, max_length=10)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Content-Type lookup for download
# ---------------------------------------------------------------------------

_CONTENT_TYPES: dict[str, str] = {
    "html": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    "md": "text/markdown; charset=utf-8",
    "json": "application/json",
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{session_id}/exports")
async def create_export_endpoint(
    session_id: str,
    body: GenerateExportBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Kick off an export render. Returns the artifact_id + status.

    For fast formats (HTML, MD) this runs sync inside the request and
    returns ``status='ready'`` immediately. The architecture supports
    async dispatch for slow formats (PPTX/PDF/XLSX) via the
    ``status='generating' → 'ready'`` transition — Day 4 wires that up
    for the slow formats.
    """
    await _require_write(session_id, user)
    try:
        req = GenerateArtifactRequest(
            session_id=UUID(session_id),
            artifact_type=body.artifact_type,
            format=body.format,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid request: {e}") from e

    triggered_by: UUID | None = None
    if user.get("user_id"):
        try:
            triggered_by = UUID(str(user["user_id"]))
        except Exception:
            triggered_by = None

    result = await generate_artifact(req, triggered_by=triggered_by)
    return {
        "artifact_id": str(result.artifact_id),
        "session_id": str(result.session_id),
        "artifact_type": result.artifact_type,
        "format": result.format,
        "status": result.status,
        "file_size_bytes": result.file_size_bytes,
        "claim_citation_count": result.claim_citation_count,
        "generation_wall_seconds": result.generation_wall_seconds,
        "failure_reason": result.failure_reason,
        "metadata": result.metadata,
    }


@router.get("/{session_id}/exports/{artifact_id}")
async def get_export_endpoint(
    session_id: str,
    artifact_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    await _require_read(session_id, user)
    try:
        row = await get_artifact(UUID(session_id), UUID(artifact_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e
    if not row:
        # Hide existence from cross-firm callers (sessions.py pattern):
        # the read permission already checked the session; if the row is
        # missing here it's either a typo or another session's artifact.
        raise HTTPException(status_code=404, detail="Artifact not found")
    return row


@router.get("/{session_id}/exports/{artifact_id}/download")
async def download_export_endpoint(
    session_id: str,
    artifact_id: str,
    user: dict = Depends(get_current_user),
):
    await _require_read(session_id, user)
    try:
        row = await get_artifact(UUID(session_id), UUID(artifact_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e
    if not row:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if row.get("status") != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Artifact not ready (status={row.get('status')!r})",
        )
    fp = row.get("file_path")
    if not fp or not os.path.exists(fp):
        raise HTTPException(status_code=410, detail="Artifact file no longer on disk")
    fmt = str(row.get("format") or "")
    media = _CONTENT_TYPES.get(fmt, "application/octet-stream")
    filename = f"{row.get('artifact_type','artifact')}.{fmt}"
    # Browser-renderable formats preview inline; binary formats (PDF,
    # PPTX, XLSX, DOCX) ship as Content-Disposition: attachment so the
    # frontend's "1-pager (PDF)" click triggers a file download.
    disposition = "inline" if fmt in ("html", "md") else "attachment"
    return FileResponse(
        Path(fp),
        media_type=media,
        filename=filename,
        content_disposition_type=disposition,
    )


@router.get("/{session_id}/exports")
async def list_exports_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    await _require_read(session_id, user)
    try:
        return await list_artifacts(UUID(session_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {e}") from e
