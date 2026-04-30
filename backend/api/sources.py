"""Source library + manual trust classification.

Endpoints:
  GET   /api/sources?engagement_id=...   list visible sources for an engagement
  GET   /api/sources/{id}                fetch one
  PATCH /api/sources/{id}                update title/trust/scope/notes
  DELETE /api/sources/{id}               remove a source
  GET   /api/library/sources             firm-wide sources (visible everywhere)
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.permissions import can_admin, can_read, can_write
from core.retrieval_chunks import hybrid_search
from storage.source_queries import (
    delete_source,
    get_source,
    list_firm_sources,
    list_visible_sources,
    update_source,
)

router = APIRouter()

TrustLevel = Literal["firm_vetted", "credible_external", "web_general", "contested"]
Scope = Literal["engagement", "firm"]


class SourcePatchBody(BaseModel):
    title: Optional[str] = Field(default=None, max_length=1024)
    trust_level: Optional[TrustLevel] = None
    scope: Optional[Scope] = None
    notes: Optional[str] = Field(default=None, max_length=4000)


@router.get("")
async def list_engagement_sources(
    engagement_id: str = Query(..., description="Engagement to list sources for"),
    user: dict = Depends(get_current_user),
) -> dict:
    if not await can_read(engagement_id, user):
        raise HTTPException(status_code=404, detail="Engagement not found")
    sources = await list_visible_sources(engagement_id)
    return {"sources": sources}


@router.get("/search")
async def search_chunks(
    engagement_id: str = Query(...),
    q: str = Query(..., min_length=1, max_length=500),
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid",
    k: int = Query(20, ge=1, le=50),
    user: dict = Depends(get_current_user),
) -> dict:
    """Hybrid retrieval over the engagement's chunks (own + firm-wide)."""
    if not await can_read(engagement_id, user):
        raise HTTPException(status_code=404, detail="Engagement not found")
    return await hybrid_search(engagement_id=engagement_id, query=q, k=k, mode=mode)


@router.get("/{source_id}")
async def get_one(source_id: str, user: dict = Depends(get_current_user)) -> dict:
    src = await get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    # Firm-scoped sources: any authenticated user can read.
    # Engagement-scoped: must have read on the engagement.
    if src["scope"] != "firm":
        if not src["session_id"] or not await can_read(src["session_id"], user):
            raise HTTPException(status_code=404, detail="Source not found")
    return {"source": src}


@router.patch("/{source_id}")
async def patch_source(
    source_id: str,
    body: SourcePatchBody,
    user: dict = Depends(get_current_user),
) -> dict:
    src = await get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")

    # Permission: writer on the source's engagement (or firm admin).
    # Promoting from engagement to firm scope requires lead role.
    if src["session_id"]:
        if body.scope == "firm" and not await can_admin(src["session_id"], user):
            raise HTTPException(status_code=403, detail="Only leads can promote to firm-wide")
        if not await can_write(src["session_id"], user):
            raise HTTPException(status_code=403, detail="No write access")
    else:
        # Firm-scoped sources without a session: only firm admins can edit.
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Firm admin required")

    try:
        updated = await update_source(
            source_id,
            title=body.title,
            trust_level=body.trust_level,
            scope=body.scope,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"source": updated}


@router.delete("/{source_id}")
async def delete_one(source_id: str, user: dict = Depends(get_current_user)) -> dict:
    src = await get_source(source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    if src["session_id"]:
        if not await can_admin(src["session_id"], user):
            raise HTTPException(status_code=403, detail="Lead-only action")
    else:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Firm admin required")
    ok = await delete_source(source_id)
    return {"deleted": bool(ok)}


# ---- Firm-wide library --------------------------------------------------

library_router = APIRouter()


@library_router.get("/sources")
async def list_library(user: dict = Depends(get_current_user)) -> dict:
    """Every firm-wide source. Visible to any authenticated user."""
    sources = await list_firm_sources()
    return {"sources": sources}
