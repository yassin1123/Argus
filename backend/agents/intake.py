"""Pre-pipeline clarifying questions (structured JSON)."""

from pydantic import BaseModel, Field

from core.demo_mode import has_openai_key, is_demo_mode
from core.inference.structured import generate_structured

# Generic clarifying questions used when DEMO_MODE=1 or no OPENAI_API_KEY is set,
# so the workspace flow stays usable without LLM calls.
_DEMO_INTAKE_QUESTIONS = [
    {
        "id": "q1",
        "question": "Who is the target audience or user for this decision?",
        "why": "Constrains the analysis to the relevant segment.",
        "input_type": "text",
        "placeholder": "e.g. mid-market B2B SaaS, retail and logistics verticals",
    },
    {
        "id": "q2",
        "question": "What is the time horizon and resource budget for this decision?",
        "why": "Bounds the recommendation against realistic execution capacity.",
        "input_type": "text",
        "placeholder": "e.g. 18 months, $2.5M, 12 headcount",
    },
    {
        "id": "q3",
        "question": "What constraints, compliance, or non-negotiables must the recommendation respect?",
        "why": "Prevents the analysis from suggesting paths that are blocked by policy or contract.",
        "input_type": "text",
        "placeholder": "e.g. GDPR data residency required; no exclusive deals",
    },
]

INTAKE_SYSTEM = """You are the Intake agent for Argus, an elite decision intelligence platform.
Your job: given a strategic question, generate 6-8 clarifying questions that would most
change the analysis if answered. The output of this intake feeds the planner, researcher, and analyst —
the more specific and dimension-spanning these questions are, the sharper the final recommendation.

DIMENSIONS TO COVER (aim to cover most of these — pick the ones most relevant to the question):
1. **Goal / success criteria** — what does winning look like in 6/12/18 months? What metric defines it?
2. **Constraints** — budget, headcount cap, hard deadlines, compliance/legal red lines, tech constraints.
3. **Current state baseline** — what's already in place? Existing customers, infrastructure, contracts, partners.
4. **Stakeholders / decision authority** — who signs off? Who is the eventual customer/user?
5. **Risk tolerance** — willing to bet the company, or cap downside at $X?
6. **Competitive context** — who are the 1-3 competitors that matter most? Any contracts that lock anything in?
7. **Why now** — what changed that makes this question urgent today vs 6 months ago?
8. **Done-before signals** — has the team or anyone in the network executed a similar play? What broke?

QUESTION RULES:
- Each question must be specific to the user's strategic question (not generic).
- Each question unlocks a DIFFERENT dimension — avoid two questions that ask the same thing differently.
- Questions are answerable in 1-3 sentences (not essays).
- Prioritise QUANTITATIVE inputs (rates, numbers, timelines, $ amounts) over qualitative ones.
- The first question should always be about the goal / success criteria.
- The last question should always probe an asymmetric risk (kill criterion or compliance red line).
- "why" must explain how the answer changes the analysis — not just "to understand context".

Output ONLY valid JSON:
{
  "questions": [
    {
      "id": "q1",
      "question": "What metric will tell you in 12 months whether this expansion succeeded?",
      "why": "Determines whether the analysis optimizes for revenue, market share, or strategic positioning.",
      "input_type": "text",
      "placeholder": "e.g. €5M ARR from EU customers; 30+ named accounts in pipeline"
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
        # Demo / no-key fallback — return canned questions so the workspace
        # flow keeps working without an LLM call.
        if is_demo_mode() or not has_openai_key():
            return {"questions": list(_DEMO_INTAKE_QUESTIONS)}

        user = (
            f"Strategic question to analyse:\n{query.strip()[:4000]}\n\n"
            "Generate 6-8 intake questions covering goal/success metric, constraints, current state, "
            "stakeholders, risk tolerance, competition, urgency, and any asymmetric risks. "
            "Each question must be specific to the strategic question above — not generic."
        )
        try:
            out, _meta = await generate_structured(
                IntakeOutput,
                task_kind="intake",
                system=INTAKE_SYSTEM,
                user=user,
            )
        except Exception:
            # Any LLM-side failure (auth, rate limit, network) → fall back to
            # demo questions rather than 500ing the page.
            return {"questions": list(_DEMO_INTAKE_QUESTIONS)}
        data = out.model_dump()
        qs = data.get("questions") or []
        for i, q in enumerate(qs):
            if not q.get("id"):
                q["id"] = f"q{i + 1}"
        return {"questions": qs[:8]}
