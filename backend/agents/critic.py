import json
from typing import TYPE_CHECKING

from core.inference.structured import generate_structured
from models.agent_structured import CriticStructuredOutput

if TYPE_CHECKING:
    from core.consulting_modes import ResolvedConsultingMode  # noqa: F401

CRITIC_SYSTEM = """
You are the Critic agent in the Argus decision system.

Your job is to challenge the analyst's recommendation rigorously.
You are a devil's advocate. You look for:
- Weak or missing evidence
- Flawed assumptions
- Alternative interpretations
- Risks not considered
- Counterarguments to the recommendation

Output ONLY valid JSON:
{
  "overall_assessment": "How strong is the analysis overall?",
  "revision_instructions": [
    {"target": "key_claims|recommendation|confidence|trade_offs|assumptions", "severity": "high|medium|low", "instruction": "What the analyst must fix"}
  ],
  "weak_points": ["Weak point 1", "Weak point 2"],
  "counterarguments": ["Counterargument 1", "Counterargument 2"],
  "missing_evidence": ["What evidence would strengthen this?"],
  "risks_missed": ["Risk 1", "Risk 2"],
  "confidence_adjustment": "Should confidence go up, down, or stay?",
  "verdict": "accept|revise|reject"
}
Be harsh but fair. Do not reject good analysis. Surface real gaps.
If revision_instructions is empty but verdict is revise, still add at least one instruction.

STRESS-TEST CHECKLIST (address in weak_points or revision_instructions):
1. Does the recommendation make a SPECIFIC, falsifiable claim? If not, flag it.
2. Does the analysis quantify the trade-off (e.g. cost vs impact)? If not, request it.
3. Are next_steps or implied actions time-bound? If not, flag as insufficient.
4. Does stated confidence match evidence depth? Downgrade if evidence is thin.
5. Is there a clear statement of what would change the recommendation? If not, require it.
"""


class CriticAgent:
    async def run(
        self,
        query: str,
        analysis: dict,
        research: dict,
        *,
        session_id: str | None = None,
        trace_id: str | None = None,
        resolved_mode: "ResolvedConsultingMode | None" = None,
    ) -> dict:
        # Mode-driven coverage block: when a resolved mode is provided
        # the critic gets the firm-overridden required_branches and
        # reasoning_slots directly in the user message, so its branch-
        # coverage and slot-population checks reflect the FIRM's policy
        # (W6/D4) rather than the flat YAML.
        coverage_block = ""
        if resolved_mode is not None:
            rb = resolved_mode.required_branches
            rs = resolved_mode.reasoning_slots
            if rb or rs:
                coverage_block = (
                    "\nCONSULTING-MODE COVERAGE EXPECTATIONS:\n"
                    f"  required_branches: {', '.join(rb) if rb else '(none)'}\n"
                    f"  reasoning_slots:   {', '.join(rs) if rs else '(none)'}\n"
                    "Flag in weak_points or revision_instructions any required\n"
                    "branch with no evidence, and any reasoning slot the analyst\n"
                    "did not populate. Use the slot_id from the analysis output.\n"
                )

        user_msg = f"""
Original query: {query}
Analyst output: {json.dumps(analysis, indent=2)}
Research used: {json.dumps(research, indent=2)[:3000]}
{coverage_block}"""
        out, _meta = await generate_structured(
            CriticStructuredOutput,
            task_kind="critic",
            system=CRITIC_SYSTEM,
            user=user_msg,
            temperature=0.5,
            session_id=session_id,
            trace_id=trace_id,
        )
        data = out.model_dump()
        if isinstance(data, dict) and data.get("verdict") == "revise":
            ri = data.get("revision_instructions")
            if not ri or not isinstance(ri, list) or len(ri) == 0:
                data["revision_instructions"] = [
                    {
                        "target": "key_claims",
                        "severity": "medium",
                        "instruction": "Tie each key claim to specific evidence ids from the catalog.",
                    }
                ]
        return data
