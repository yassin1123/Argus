"""Artifacts API — create, get, list, update, export."""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from agents.memo_builder import build_memo_document, collect_chunk_ids
from auth.dependencies import get_current_user
from auth.permissions import can_admin, can_read, can_write
from deliverables.docx_renderer import render_memo_to_docx
from db.queries import get_report
from models.structured_answer import StructuredAnswer
from storage.artifact_queries import (
    delete_artifact,
    get_artifact,
    insert_artifact,
    list_artifacts_for_engagement,
    update_artifact,
)
from storage.chunk_queries import list_chunks_for_session

router = APIRouter()


# ---- Schemas ----

class CreateArtifactBody(BaseModel):
    engagement_id: str
    type: Literal["memo", "deck", "model", "chart"] = "memo"
    title: Optional[str] = Field(default=None, max_length=512)


class PatchArtifactBody(BaseModel):
    title: Optional[str] = Field(default=None, max_length=512)
    status: Optional[Literal["draft", "review", "final"]] = None
    document_json: Optional[dict] = None


# ---- Helpers ----

async def _require_artifact(
    artifact_id: str, user: dict, *, capability: str
) -> dict:
    art = await get_artifact(artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    eng = art["engagement_id"]
    ok = (
        await can_read(eng, user)
        if capability == "read"
        else await can_write(eng, user)
        if capability == "write"
        else await can_admin(eng, user)
    )
    if not ok:
        raise HTTPException(
            status_code=404 if capability == "read" else 403,
            detail="Artifact not accessible",
        )
    return art


# ---- Endpoints ----

@router.get("")
async def list_artifacts(
    engagement_id: str = Query(..., description="Engagement to list artifacts for"),
    user: dict = Depends(get_current_user),
) -> dict:
    if not await can_read(engagement_id, user):
        raise HTTPException(status_code=404, detail="Engagement not found")
    arts = await list_artifacts_for_engagement(engagement_id)
    # Don't ship full document_json in the list view — clients fetch it on open.
    light = [
        {**a, "document_json": None, "preview_size": len(str(a.get("document_json") or {}))}
        for a in arts
    ]
    return {"artifacts": light}


@router.post("", status_code=201)
async def create_artifact(
    body: CreateArtifactBody,
    user: dict = Depends(get_current_user),
) -> dict:
    """Materialize an artifact from the engagement's StructuredAnswer."""
    if not await can_write(body.engagement_id, user):
        raise HTTPException(status_code=403, detail="No write access on this engagement")

    if body.type != "memo":
        # MVP only ships memo. Decks/models/charts are stubbed for v1.
        raise HTTPException(status_code=400, detail=f"Artifact type '{body.type}' not supported in MVP — memo only.")

    report = await get_report(body.engagement_id)
    if not report:
        raise HTTPException(
            status_code=409,
            detail="Engagement has no completed report yet — run the pipeline first.",
        )
    sa_dict = report.get("structured_answer")
    if not sa_dict or not sa_dict.get("sections"):
        raise HTTPException(
            status_code=409,
            detail="No StructuredAnswer to base the memo on. Re-run the pipeline.",
        )

    answer = StructuredAnswer.model_validate(sa_dict)

    # Pull chunks for the appendix labels.
    chunks = await list_chunks_for_session(body.engagement_id, limit=200)
    titles_by_chunk = {
        c["id"]: (
            f"{c.get('source_filename') or 'Source'}"
            + (f" — p.{c['page']}" if c.get("page") else "")
            + (f" · § {c['section_heading']}" if c.get("section_heading") else "")
        )
        for c in chunks
    }

    document = build_memo_document(answer, source_titles_by_chunk=titles_by_chunk)
    title = body.title or report.get("recommendation", "Memo")[:120] or "Memo"

    art = await insert_artifact(
        engagement_id=body.engagement_id,
        type_=body.type,
        title=title,
        document_json=document,
        source_report_id=report.get("id"),
        created_by=user["user_id"],
        status="draft",
    )
    return {"artifact": art}


@router.get("/{artifact_id}")
async def get_one(artifact_id: str, user: dict = Depends(get_current_user)) -> dict:
    art = await _require_artifact(artifact_id, user, capability="read")
    return {"artifact": art}


@router.patch("/{artifact_id}")
async def patch_one(
    artifact_id: str,
    body: PatchArtifactBody,
    user: dict = Depends(get_current_user),
) -> dict:
    art = await _require_artifact(artifact_id, user, capability="write")
    try:
        updated = await update_artifact(
            artifact_id,
            title=body.title,
            status=body.status,
            document_json=body.document_json,
            updated_by=user["user_id"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"artifact": updated}


@router.delete("/{artifact_id}")
async def delete_one(artifact_id: str, user: dict = Depends(get_current_user)) -> dict:
    art = await _require_artifact(artifact_id, user, capability="admin")
    ok = await delete_artifact(artifact_id)
    return {"deleted": bool(ok)}


@router.get("/{artifact_id}/export")
async def export_artifact(
    artifact_id: str,
    format: Literal["docx"] = Query("docx"),
    user: dict = Depends(get_current_user),
) -> Response:
    art = await _require_artifact(artifact_id, user, capability="read")
    if art["type"] != "memo":
        raise HTTPException(status_code=400, detail="Only memo export is supported in MVP")
    if format != "docx":
        raise HTTPException(status_code=400, detail="Only docx export is supported in MVP")

    # Build the sources appendix from the chunks referenced in the memo.
    chunk_ids = _collect_chunk_ids_from_doc(art["document_json"])
    chunks = await list_chunks_for_session(art["engagement_id"], limit=200)
    chunks_by_id = {c["id"]: c for c in chunks}
    appendix: list[dict[str, Any]] = []
    for n, cid in enumerate(chunk_ids, start=1):
        c = chunks_by_id.get(cid)
        if not c:
            continue
        appendix.append(
            {
                "n": n,
                "label": c.get("source_filename") or "Source",
                "page": c.get("page"),
                "url": c.get("source_url"),
                "snippet": (c.get("content") or "")[:300],
            }
        )

    docx_bytes = render_memo_to_docx(
        document_json=art["document_json"],
        title=art["title"],
        sources_appendix=appendix,
    )
    filename = f"{art['title'][:60].replace('/', '_')}.docx"
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _collect_chunk_ids_from_doc(document_json: dict) -> list[str]:
    """Walk the ProseMirror tree and collect chunk_ids in [N] order."""
    seen: dict[str, None] = {}

    def walk(node: dict) -> None:
        if isinstance(node, dict):
            for mark in node.get("marks") or []:
                if mark.get("type") == "citation":
                    for cid in (mark.get("attrs") or {}).get("chunk_ids") or []:
                        if cid not in seen:
                            seen[cid] = None
            for child in node.get("content") or []:
                walk(child)

    walk(document_json or {})
    return list(seen.keys())
