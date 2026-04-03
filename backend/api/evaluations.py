"""Evaluation metrics export for regression and ops review."""

from fastapi import APIRouter, HTTPException, Query

from db.queries import get_session_row, list_evaluations_for_session

router = APIRouter()


@router.get("/export")
async def export_evaluations(session_id: str = Query(..., description="Session UUID")) -> dict:
    row = await get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    ev = await list_evaluations_for_session(session_id)
    return {
        "session_id": session_id,
        "pipeline_state": row.get("pipeline_state"),
        "report_mode": row.get("report_mode"),
        "evaluations": ev,
    }
