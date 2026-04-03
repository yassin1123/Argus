from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agents.conversation import ConversationAgent
from core.limits import limiter
from db.queries import (
    append_conversation_turn,
    get_session_row,
    list_conversation_turns,
    update_session_status,
)
from tasks.pipeline import run_partial_pipeline_task

router = APIRouter()


class ChatMessageBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=12000)


@router.get("/{session_id}/chat")
async def get_chat_history(session_id: str) -> list[dict]:
    row = await get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return await list_conversation_turns(session_id)


@router.post("/{session_id}/chat")
@limiter.limit("60/hour")
async def post_chat_message(request: Request, session_id: str, body: ChatMessageBody) -> dict:
    row = await get_session_row(session_id)
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    msg = body.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Empty message")

    await append_conversation_turn(session_id, "user", msg, intent=None, metadata={})
    history = await list_conversation_turns(session_id)
    hist_for_model = [{"role": h["role"], "content": h["content"]} for h in history[:-1]]

    agent = ConversationAgent()
    result = await agent.run(hist_for_model, msg, str(row.get("query") or ""))

    reply = str(result.get("reply") or "").strip() or "I'm processing that."
    intent = str(result.get("intent") or "clarify")
    pt = result.get("pipeline_trigger") or {}
    ptype = str(pt.get("type") or "none").lower() if isinstance(pt, dict) else "none"

    assistant_meta = {
        "intent": intent,
        "pipeline_trigger": pt if isinstance(pt, dict) else {},
        "follow_up_question": str(result.get("follow_up_question") or ""),
    }
    turn = await append_conversation_turn(
        session_id, "assistant", reply, intent=intent, metadata=assistant_meta
    )

    pipeline_triggered = False
    if ptype in ("light", "full", "partial"):
        pipeline_triggered = True
        await update_session_status(session_id, "processing")
        run_partial_pipeline_task.delay(session_id, [ptype], pt.get("focus") if isinstance(pt, dict) else None)

    return {
        "reply": reply,
        "pipeline_triggered": pipeline_triggered,
        "turn_id": turn["id"],
        "intent": intent,
        "follow_up_question": assistant_meta.get("follow_up_question") or "",
    }
