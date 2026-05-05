import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from auth.dependencies import get_current_user
from auth.permissions import (
    add_membership,
    can_admin,
    can_read,
    can_write,
    get_engagement_role,
)
from core.limits import limiter
from core.text_normaliser import normalise_query
from agents.intake import IntakeAgent
from db.queries import (
    clear_pipeline_artifacts,
    create_session,
    delete_session,
    get_session_detail,
    get_session_row,
    list_sessions,
    save_session_intake_answers,
    save_session_intake_questions,
    update_session_status,
)
from models.session import CreateSessionRequest, IntakeSubmitRequest
from tasks.pipeline import run_pipeline_task

router = APIRouter()


async def _require_read(session_id: str, user: dict) -> None:
    if not await can_read(session_id, user):
        raise HTTPException(status_code=404, detail="Session not found")


async def _require_write(session_id: str, user: dict) -> None:
    if not await can_write(session_id, user):
        raise HTTPException(status_code=403, detail="Read-only access on this engagement")


async def _require_admin(session_id: str, user: dict) -> None:
    if not await can_admin(session_id, user):
        raise HTTPException(status_code=403, detail="Lead-only action")


@router.get("")
async def list_sessions_endpoint(user: dict = Depends(get_current_user)) -> list[dict]:
    if user.get("role") == "admin":
        return await list_sessions()
    return await list_sessions(user_id=user["user_id"])


@router.post("")
@limiter.limit("30/hour")
async def create_session_endpoint(
    request: Request,
    body: CreateSessionRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    try:
        q = normalise_query(body.query)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    session_id = str(uuid.uuid4())
    title = (body.title or q)[:200]
    mode = (body.report_mode or "general").strip().lower().replace(" ", "_")[:64] or "general"
    await create_session(
        session_id, title, q, status="draft", report_mode=mode,
        created_by_user_id=user["user_id"],
    )
    return {"session_id": session_id, "status": "draft", "report_mode": mode, "my_role": "lead"}


@router.post("/{session_id}/intake/generate")
@limiter.limit("60/hour")
async def intake_generate_questions(
    request: Request,
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    row = await get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    await _require_write(session_id, user)
    agent = IntakeAgent()
    data = await agent.generate_questions(row["query"])
    await save_session_intake_questions(session_id, data.get("questions") or [])
    return data


@router.post("/{session_id}/intake/submit")
@limiter.limit("60/hour")
async def intake_submit_answers(
    request: Request,
    session_id: str,
    body: IntakeSubmitRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    if not await get_session_row(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    await _require_write(session_id, user)
    payload = [a.model_dump() for a in body.answers]
    await save_session_intake_answers(session_id, payload)
    return {"ok": True, "saved": len(payload)}


@router.get("/{session_id}")
async def get_session_endpoint(session_id: str, user: dict = Depends(get_current_user)) -> dict:
    """Session detail with the user's role on the engagement attached."""
    data = await get_session_detail(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    await _require_read(session_id, user)
    role = await get_engagement_role(session_id, user["user_id"])
    if role is None and user.get("role") == "admin":
        role = "lead"
    data["my_role"] = role
    return data


@router.delete("/{session_id}")
async def delete_session_endpoint(session_id: str, user: dict = Depends(get_current_user)) -> dict:
    if not await get_session_row(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    await _require_admin(session_id, user)
    ok = await delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


@router.post("/{session_id}/run")
@limiter.limit("30/hour")
async def run_session_endpoint(
    request: Request,
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """Idempotent guard: duplicate run requests while `processing` return 409."""
    row = await get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    await _require_write(session_id, user)
    if row["status"] == "processing":
        raise HTTPException(status_code=409, detail="Session is already processing")
    if row["status"] in ("failed", "insufficient", "complete"):
        await clear_pipeline_artifacts(session_id)
    try:
        normalise_query(row["query"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await update_session_status(session_id, "processing")
    run_pipeline_task.delay(session_id)
    return {"session_id": session_id, "status": "processing"}
