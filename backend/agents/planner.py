from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.inference.structured import generate_structured

PLANNER_SYSTEM = """
You are the Planner agent in the Argus decision system.
Your job is to take a complex question and break it into a structured
research plan. You do not answer the question. You plan how to answer
it.
Output ONLY valid JSON in this exact format:
{
  "objective": "Clear statement of what we are trying to decide",
  "tasks": [
    {
      "id": 1,
      "question": "Specific sub-question to research",
      "type": "factual|comparative|quantitative|qualitative",
      "priority": "high|medium|low",
      "why_it_matters": "Why this question is relevant to the decision"
    }
  ],
  "decision_criteria": ["Criterion 1", "Criterion 2"],
  "scope": "What is in and out of scope for this analysis"
}
Generate 4-8 tasks. Be specific. Do not be vague.

COMPARATIVE DECISIONS (when the user compares options A vs B):
- Include at least 2 tasks that explicitly research Option A / path A.
- Include at least 2 tasks that explicitly research Option B / path B.
- Include at least 1 task on decision criteria (what factors matter most).
- Include at least 1 task on what evidence would change the answer.
- Avoid tasks so broad that web search cannot answer them; prefer specific, quantitative sub-questions.
"""


class PlannerTask(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int = 0
    question: str = ""
    type: str = "factual"
    priority: str = "medium"
    why_it_matters: str = ""

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v: object) -> int:
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        return 0


class PlannerOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    objective: str = ""
    tasks: list[PlannerTask] = Field(default_factory=list)
    decision_criteria: list[str] = Field(default_factory=list)
    scope: str = ""

    @field_validator("decision_criteria", mode="before")
    @classmethod
    def coerce_criteria(cls, v: object) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v if str(x).strip()]
        return [str(v)]


class PlannerAgent:
    async def run(
        self,
        query: str,
        context: str,
        *,
        report_mode: str | None = None,
        intake_block: str = "",
    ) -> dict:
        hint = ""
        if report_mode and report_mode != "general":
            from core.consulting_modes import get_mode_config

            cfg = get_mode_config(report_mode)
            rb = cfg.get("required_branches") or []
            if rb:
                hint = (
                    f"\nConsulting mode '{report_mode}': ensure tasks collectively cover these "
                    f"research dimensions: {', '.join(rb)}.\n"
                )
        prefix = ""
        ib = (intake_block or "").strip()
        if ib:
            prefix = f"User context (from intake):\n{ib[:4000]}\n\n"
        user_message = f"{prefix}Query: {query}\n\nContext available:\n{context[:3000]}{hint}"
        out, _meta = await generate_structured(
            PlannerOutput,
            task_kind="planner",
            system=PLANNER_SYSTEM,
            user=user_message,
        )
        data = out.model_dump()
        for i, t in enumerate(data.get("tasks") or []):
            if not t.get("id"):
                t["id"] = i + 1
        return data
