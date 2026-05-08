from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.inference.structured import generate_structured

# Source kinds the researcher knows how to route to. Keep this list tight —
# every value must map to a real retrieval path:
#   uploaded   → chunks table source_type filter
#   sec_filing → chunks table source_type filter (US public-company filings)
#   ch_filing  → chunks table source_type filter (UK Companies House filings)
#   news       → Tavily lazy-fetch + chunks table source_type filter
#   web        → web-search provider (snippet-only, no chunked verification)
SourceKind = Literal["uploaded", "sec_filing", "ch_filing", "news", "web"]

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
      "why_it_matters": "Why this question is relevant to the decision",
      "source_priorities": ["sec_filing", "uploaded"]
    }
  ],
  "decision_criteria": ["Criterion 1", "Criterion 2"],
  "scope": "What is in and out of scope for this analysis"
}
Generate 4-8 tasks. Be specific. Do not be vague.

SOURCE PRIORITIES (per task)
For each task, emit "source_priorities" as an ordered list of source kinds
the researcher should query. Pick the smallest set that can actually answer
the task. The researcher reads them in order and spills to the next kind
when the first returns too few hits.

Source kinds:
  - "uploaded"   — documents the user uploaded for this engagement
                   (CIMs, board decks, internal memos). Use whenever the
                   answer should be grounded in the user's own materials.
  - "sec_filing" — SEC EDGAR filings (10-K / 10-Q / 8-K / DEF 14A / S-1).
                   Best for U.S. public-company financials, risk factors,
                   MD&A, and segment data.
  - "ch_filing"  — UK Companies House annual accounts. Use whenever the
                   subject is a UK-registered company (Tesco, Marks &
                   Spencer, AstraZeneca, BT Group, Unilever, Shell PLC,
                   etc.). The brief mentioning "UK", "British",
                   "Companies House", a UK FTSE listing, or a UK company
                   number is a strong signal.
  - "news"       — recent news, press releases, analyst notes. Use when
                   freshness or market reaction matters.
  - "web"        — open web search. Use for breadth, third-party data,
                   industry stats, or anything the above sources won't
                   cover.

Examples:
  - "Apple iPhone segment revenue trend FY2024"      → ["sec_filing", "uploaded"]
  - "Recent analyst reaction to the Q3 print"        → ["news", "web"]
  - "Key risks called out in the CIM"                → ["uploaded"]
  - "TAM for managed-services in EMEA, 2025"         → ["web"]
  - "Tesco UK grocery margin trend"                  → ["ch_filing", "news"]
  - "AstraZeneca pipeline disclosures"               → ["ch_filing", "sec_filing"]

If a task could be answered by either uploaded materials or SEC filings,
list "uploaded" first when the user is the deal owner; list "sec_filing"
first when the question is about the public-company filer. For UK-
registered companies prefer "ch_filing" over "sec_filing" even when the
firm has a US listing — Companies House accounts are the statutory
primary, the SEC filing is downstream.

If you genuinely cannot decide, omit "source_priorities" — the researcher
will fall back to legacy behaviour.

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
    # When None, the researcher falls back to its legacy retrieval path
    # (vector-only over uploaded chunks + always-on web if SERPAPI_KEY).
    source_priorities: list[SourceKind] | None = None

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

    @field_validator("source_priorities", mode="before")
    @classmethod
    def coerce_source_priorities(cls, v: object) -> list[str] | None:
        # Accept None, [], or list of strings; drop unknown kinds rather
        # than reject the whole task so a single typo from the model
        # doesn't blow up the plan.
        if v is None:
            return None
        if not isinstance(v, list):
            return None
        valid = {"uploaded", "sec_filing", "ch_filing", "news", "web"}
        out: list[str] = []
        seen: set[str] = set()
        for item in v:
            s = str(item).strip().lower().replace("-", "_").replace(" ", "_")
            if s in valid and s not in seen:
                out.append(s)
                seen.add(s)
        return out or None


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
