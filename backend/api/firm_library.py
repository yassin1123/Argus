"""Firm library API.

Endpoints (all under ``/api/firms/{firm_id}/library``):

  POST   /                       upload + metadata           (admin)
  GET    /                       list (with filters)         (member)
  GET    /{content_id}           one record + chunk preview  (member)
  POST   /{content_id}           metadata edit               (admin)
  POST   /{content_id}/retire    soft-delete                 (admin)

Day 3 wires real role gates: any member can read; only admins can
mutate. Cross-firm reads return 404 (not 403) so non-members can't
enumerate firms by probing. Failed attempts are audited at the domain
level (action='firm_library.list_unauthorized_attempt' /
'firm_library.admin_unauthorized_attempt') in addition to the HTTP-
level audit middleware row.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, UploadFile
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.firm_permissions import (
    require_firm_admin,
    require_firm_member,
)
from core.firm_library import (
    UnsupportedFileTypeError,
    ingest_firm_content,
    retire_firm_content,
)
from core.firm_library.service import list_chunks_for_content
from db.connection import acquire
from storage.firm_content_queries import (
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
# Domain-rich audit helpers
# ---------------------------------------------------------------------------


async def _audit_event(
    *,
    user: dict,
    action: str,
    firm_id: str,
    content_id: str | None,
    payload: dict[str, Any],
) -> None:
    """Best-effort domain-level audit row. Never raises."""
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_events (
                    actor_user_id, actor_email, action, resource_type,
                    resource_id, payload
                ) VALUES (
                    $1::uuid, $2, $3, 'firm_content', $4, $5::jsonb
                )
                """,
                user.get("user_id"),
                user.get("email"),
                action,
                content_id,
                json.dumps({"firm_id": firm_id, **payload}),
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("audit_event %s skipped: %s", action, e)


def _diff_metadata(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Return only the fields that changed between two firm_content rows.

    Used for the firm_library.metadata_edit audit payload. Compares the
    four mutable fields (title, description, intended_modes,
    sector_tags); everything else is immutable per spec.
    """
    keys = ("title", "description", "intended_modes", "sector_tags")
    out: dict[str, Any] = {}
    for k in keys:
        b = before.get(k)
        a = after.get(k)
        if b != a:
            out[k] = {"before": b, "after": a}
    return out


# ---------------------------------------------------------------------------
# POST / — upload (admin only)
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
    # Two-tier check: prove membership (404 if not), then prove admin
    # (403 if not). Each check audits its own denial, so the trail is
    # specific to the failure mode.
    await require_firm_member(firm_id, user)
    await require_firm_admin(firm_id, user)

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
    await _audit_event(
        user=user,
        action="firm_library.upload",
        firm_id=firm_id,
        content_id=result.firm_content_id,
        payload={
            "title": title,
            "category": category,
            "chunks_written": result.chunks_written,
            "cached": result.cached,
            "source_filename": file.filename,
        },
    )
    return {
        "firm_content": fc,
        "ingest": {
            "cached": result.cached,
            "chunks_written": result.chunks_written,
        },
    }


# ---------------------------------------------------------------------------
# GET / — list (member)
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
    await require_firm_member(firm_id, user)
    rows = await list_firm_content(
        firm_id,
        category=category,
        sector=sector,
        mode=mode,
        include_retired=include_retired,
    )
    return {"firm_content": rows}


# ---------------------------------------------------------------------------
# GET /{content_id} — one + chunk preview (member)
# ---------------------------------------------------------------------------


@router.get("/{content_id}")
async def get_one(
    firm_id: str = Path(...),
    content_id: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await require_firm_member(firm_id, user)
    fc = await get_firm_content(firm_id, content_id)
    if not fc:
        raise HTTPException(status_code=404, detail="Firm content not found")
    preview = await list_chunks_for_content(firm_id, content_id, limit=3)
    return {"firm_content": fc, "chunk_preview": preview}


# ---------------------------------------------------------------------------
# POST /{content_id} — metadata edit (admin)
# ---------------------------------------------------------------------------


@router.post("/{content_id}")
async def edit_metadata(
    body: FirmContentEditBody,
    firm_id: str = Path(...),
    content_id: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await require_firm_member(firm_id, user)
    await require_firm_admin(firm_id, user)
    before = await get_firm_content(firm_id, content_id)
    if not before:
        raise HTTPException(status_code=404, detail="Firm content not found")
    updated = await update_firm_content(
        firm_id,
        content_id,
        title=body.title,
        description=body.description,
        intended_modes=body.intended_modes,
        sector_tags=body.sector_tags,
    )
    diff = _diff_metadata(before or {}, updated or {})
    if diff:
        await _audit_event(
            user=user,
            action="firm_library.metadata_edit",
            firm_id=firm_id,
            content_id=content_id,
            payload={"diff": diff},
        )
    return {"firm_content": updated}


# ---------------------------------------------------------------------------
# POST /{content_id}/retire — soft-delete (admin)
# ---------------------------------------------------------------------------


@router.post("/{content_id}/retire")
async def retire_endpoint(
    firm_id: str = Path(...),
    content_id: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await require_firm_member(firm_id, user)
    await require_firm_admin(firm_id, user)
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
