"""Firm library API (Phase 2 / Week 5 / Day 1).

Endpoints (all under ``/api/firms/{firm_id}/library``):

  POST   /                       upload + metadata
  GET    /                       list (with category/sector/mode filters)
  GET    /{content_id}           one record + first-3-chunk preview
  POST   /{content_id}           metadata edit (title/description/modes/sectors)
  POST   /{content_id}/retire    soft-delete

Day 1 contract: every endpoint checks firm membership; 403 on mismatch.
Role-gated actions (admin-only retire, etc.) come Day 3.
"""

from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.firm_permissions import is_firm_member
from core.firm_library import (
    SUPPORTED_EXTENSIONS,
    UnsupportedFileTypeError,
    ingest_firm_content,
    retire_firm_content,
)
from core.firm_library.service import list_chunks_for_content
from storage.firm_content_queries import (
    CATEGORIES,
    get_firm_content,
    list_firm_content,
    update_firm_content,
)

logger = logging.getLogger(__name__)
router = APIRouter()

Category = Literal[
    "playbook", "sector_primer", "prior_report", "framework", "methodology", "other"
]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FirmContentEditBody(BaseModel):
    title: Optional[str] = Field(default=None, max_length=512)
    description: Optional[str] = Field(default=None, max_length=4000)
    intended_modes: Optional[list[str]] = None
    sector_tags: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Membership guard
# ---------------------------------------------------------------------------


async def _assert_firm_member(firm_id: str, user: dict) -> None:
    if not await is_firm_member(firm_id, user):
        # 404 rather than 403 so non-members can't enumerate firms.
        raise HTTPException(status_code=404, detail="Firm not found")


# ---------------------------------------------------------------------------
# POST / — upload
# ---------------------------------------------------------------------------


@router.post("")
async def upload_firm_content(
    firm_id: str = Path(..., description="UUID of the firm"),
    title: str = Form(..., max_length=512),
    category: Category = Form(...),
    description: Optional[str] = Form(default=None, max_length=4000),
    intended_modes: Optional[str] = Form(
        default=None,
        description="Comma-separated list of consulting modes this content applies to.",
    ),
    sector_tags: Optional[str] = Form(
        default=None,
        description="Comma-separated list of sector tags (e.g. 'retail,fintech').",
    ),
    file: UploadFile = File(..., description="PDF / DOCX / MD / TXT"),
    user: dict = Depends(get_current_user),
) -> dict:
    await _assert_firm_member(firm_id, user)

    if not file.filename:
        raise HTTPException(status_code=400, detail="file is required")
    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="empty file body")

    modes = [m.strip() for m in (intended_modes or "").split(",") if m.strip()]
    sectors = [s.strip() for s in (sector_tags or "").split(",") if s.strip()]

    try:
        result = await ingest_firm_content(
            firm_id=firm_id,
            title=title,
            category=category,  # type: ignore[arg-type]
            file_bytes=body,
            source_filename=file.filename,
            uploaded_by=user.get("user_id"),
            description=description,
            intended_modes=modes,
            sector_tags=sectors,
        )
    except UnsupportedFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    fc = await get_firm_content(firm_id, result.firm_content_id)
    return {
        "firm_content": fc,
        "ingest": {
            "cached": result.cached,
            "chunks_written": result.chunks_written,
        },
    }


# ---------------------------------------------------------------------------
# GET / — list
# ---------------------------------------------------------------------------


@router.get("")
async def list_endpoint(
    firm_id: str = Path(...),
    category: Optional[Category] = Query(default=None),
    sector: Optional[str] = Query(default=None, max_length=80),
    mode: Optional[str] = Query(default=None, max_length=80),
    include_retired: bool = Query(default=False),
    user: dict = Depends(get_current_user),
) -> dict:
    await _assert_firm_member(firm_id, user)
    rows = await list_firm_content(
        firm_id,
        category=category,
        sector=sector,
        mode=mode,
        include_retired=include_retired,
    )
    return {"firm_content": rows}


# ---------------------------------------------------------------------------
# GET /{content_id} — one + chunk preview
# ---------------------------------------------------------------------------


@router.get("/{content_id}")
async def get_one(
    firm_id: str = Path(...),
    content_id: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await _assert_firm_member(firm_id, user)
    fc = await get_firm_content(firm_id, content_id)
    if not fc:
        raise HTTPException(status_code=404, detail="Firm content not found")
    preview = await list_chunks_for_content(firm_id, content_id, limit=3)
    return {"firm_content": fc, "chunk_preview": preview}


# ---------------------------------------------------------------------------
# POST /{content_id} — metadata edit (POST not PATCH per spec)
# ---------------------------------------------------------------------------


@router.post("/{content_id}")
async def edit_metadata(
    body: FirmContentEditBody,
    firm_id: str = Path(...),
    content_id: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await _assert_firm_member(firm_id, user)
    fc = await get_firm_content(firm_id, content_id)
    if not fc:
        raise HTTPException(status_code=404, detail="Firm content not found")
    updated = await update_firm_content(
        firm_id,
        content_id,
        title=body.title,
        description=body.description,
        intended_modes=body.intended_modes,
        sector_tags=body.sector_tags,
    )
    return {"firm_content": updated}


# ---------------------------------------------------------------------------
# POST /{content_id}/retire — soft-delete
# ---------------------------------------------------------------------------


@router.post("/{content_id}/retire")
async def retire_endpoint(
    firm_id: str = Path(...),
    content_id: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await _assert_firm_member(firm_id, user)
    fc = await retire_firm_content(
        firm_id=firm_id,
        content_id=content_id,
        retired_by=user.get("user_id"),
    )
    if not fc:
        # Either doesn't exist for this firm, or already retired.
        existing = await get_firm_content(firm_id, content_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Firm content not found")
        return {"firm_content": existing, "already_retired": True}
    return {"firm_content": fc, "already_retired": False}
