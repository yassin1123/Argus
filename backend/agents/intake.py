"""Pre-pipeline clarifying questions (structured JSON)."""

from pydantic import BaseModel, Field

from core.inference.structured import generate_structured

INTAKE_SYSTEM = """You are the Intake agent for Argus, an elite decision intelligence platform.
Your job: given a strategic question, generate exactly 3-5 clarifying questions that would most
change the analysis if answered.

Rules:
- Questions must be specific, not generic ("What is your churn rate?" not "Tell me more")
- Each question should unlock a different dimension of the analysis
- Questions should be answerable in 1-2 sentences
- Prioritise quantitative inputs (rates, numbers, timelines) over qualitative

Output ONLY valid JSON:
{
  "questions": [
    {
      "id": "q1",
      "question": "What is your current monthly churn rate?",
      "why": "This determines whether retention or growth is the higher-leverage lever",
      "input_type": "number_or_text",
      "placeholder": "e.g. 3.5% monthly"
    }
  ]
}
"""


class IntakeQuestionItem(BaseModel):
    id: str = ""
    question: str = ""
    why: str = ""
    input_type: str = "number_or_text"
    placeholder: str = ""


class IntakeOutput(BaseModel):
    questions: list[IntakeQuestionItem] = Field(default_factory=list)


class IntakeAgent:
    async def generate_questions(self, query: str) -> dict:
        user = f"Strategic question to analyse:\n{query.strip()[:4000]}\n\nGenerate 3-5 intake questions."
        out, _meta = await generate_structured(
            IntakeOutput,
            task_kind="intake",
            system=INTAKE_SYSTEM,
            user=user,
        )
        data = out.model_dump()
        qs = data.get("questions") or []
        for i, q in enumerate(qs):
            if not q.get("id"):
                q["id"] = f"q{i + 1}"
        return {"questions": qs[:8]}
