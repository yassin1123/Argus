"""Lightweight conversational router on top of the Argus pipeline (MVP)."""

from typing import Any

from pydantic import BaseModel, Field

from core.inference.structured import generate_structured

CONVERSATION_SYSTEM = """You are Argus, an elite strategic research analyst assistant.
Personality: direct, confident. Ask at most ONE clarifying question when essential.
When you lack data, say so and offer to run deeper research.

Capabilities (internal routing — user does not see these labels):
- clarify: answer or ask one question; no pipeline
- research: user wants more web-style research (maps to pipeline in MVP)
- analyse: user wants a full structured report run
- followup: user refines prior analysis (maps to pipeline re-run in MVP)

Rules:
- Never invent statistics or sources not in the conversation or prior report summary.
- Keep the conversational reply concise.
- If you will trigger research, say briefly what you will look into.

Output ONLY valid JSON:
{
  "intent": "clarify|research|analyse|followup",
  "reply": "text shown to the user immediately",
  "pipeline_trigger": {
    "type": "none|light|full|partial",
    "focus": "short phrase what to research if not none",
    "stage_to_rerun": ""
  },
  "follow_up_question": "optional single follow-up suggestion for the UI"
}
"""


class PipelineTriggerModel(BaseModel):
    model_config = {"extra": "ignore"}

    type: str = "none"
    focus: str = ""
    stage_to_rerun: str = ""


class ConversationModel(BaseModel):
    model_config = {"extra": "ignore"}

    intent: str = "clarify"
    reply: str = ""
    pipeline_trigger: PipelineTriggerModel = Field(default_factory=PipelineTriggerModel)
    follow_up_question: str = ""


class ConversationAgent:
    async def run(self, history: list[dict[str, Any]], latest_user: str, session_query: str) -> dict[str, Any]:
        hist_lines: list[str] = []
        for h in history[-24:]:
            role = str(h.get("role", ""))
            content = str(h.get("content", ""))[:2000]
            hist_lines.append(f"{role}: {content}")
        hist_block = "\n".join(hist_lines) if hist_lines else "(no prior turns)"
        user_block = f"""
Session research question (context):
{session_query[:3000]}

Conversation so far:
{hist_block}

Latest user message:
{latest_user[:4000]}
"""
        out, _meta = await generate_structured(
            ConversationModel,
            task_kind="conversation",
            system=CONVERSATION_SYSTEM,
            user=user_block,
        )
        data = out.model_dump()
        pt = data.get("pipeline_trigger") or {}
        if isinstance(pt, dict):
            data["pipeline_trigger"] = {
                "type": str(pt.get("type") or "none"),
                "focus": str(pt.get("focus") or ""),
                "stage_to_rerun": str(pt.get("stage_to_rerun") or ""),
            }
        return data
