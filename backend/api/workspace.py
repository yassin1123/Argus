import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.evidence_graph import build_ui_evidence_graph
from core.limits import limiter
from db.queries import get_session_row, list_pipeline_events_after
from presentations.workspace import build_workspace_payload

router = APIRouter()


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str) -> dict:
    """Primary contract for the session UI: detail rows plus `presentation` labels."""
    data = await build_workspace_payload(workspace_id)
    if not data:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return data


@router.get("/{workspace_id}/events")
async def workspace_event_stream(request: Request, workspace_id: str) -> StreamingResponse:
    """Server-sent events: new `pipeline_events` rows for this workspace (poll fallback in worker)."""
    row = await get_session_row(workspace_id)
    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")

    async def gen():
        after_id = 0
        try:
            while True:
                if await request.is_disconnected():
                    break
                batch = await list_pipeline_events_after(workspace_id, after_id=after_id, limit=100)
                for ev in batch:
                    after_id = max(after_id, int(ev["id"]))
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise

    headers = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
    return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)


@router.get("/{workspace_id}/evidence")
@limiter.limit("120/minute")
async def get_workspace_evidence(request: Request, workspace_id: str) -> dict:
    """Smaller payload: presentation evidence rail + raw evidence_objects."""
    data = await build_workspace_payload(workspace_id)
    if not data:
        raise HTTPException(status_code=404, detail="Workspace not found")
    pres = data.get("presentation") or {}
    return {
        "evidence_presentation": pres.get("evidence"),
        "evidence_objects": data.get("evidence_objects") or [],
    }


@router.get("/{workspace_id}/graph")
@limiter.limit("120/minute")
async def get_workspace_graph(request: Request, workspace_id: str) -> dict:
    """Normalized evidence graph (claims ↔ evidence ↔ sources) for the UI tab."""
    data = await build_workspace_payload(workspace_id)
    if not data:
        raise HTTPException(status_code=404, detail="Workspace not found")
    report = data.get("report") or {}
    return build_ui_evidence_graph(
        reasoning_graph=report.get("reasoning_graph") or {},
        evidence_objects=data.get("evidence_objects") or [],
        claim_support_rows=report.get("claim_support") or [],
        consulting_payload=report.get("consulting_payload") or {},
    )
