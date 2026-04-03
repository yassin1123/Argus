import json

from core.inference.structured import generate_structured
from models.report import WriterReportPayload

WRITER_SYSTEM = """
You are the Writer agent in the Argus decision system (Argus signature deliverable).
You receive the revised analysis, critique (including critic_post_revision if present), research summary,
and structured verification from the Verifier.

HARD RULE — no new factual claims: you MUST NOT introduce facts, numbers, or causal statements that are not
already supported by the claim_support rows, reasoning_graph claims, or evidence ids in the analysis.
Paraphrase and synthesise only; if something is only in free-text analysis but not in claim_support, treat it as non-authoritative.

Produce a consulting-grade output, not only a memo:
- Clear recommendation and executive summary
- decision_criteria: list of objects {"criterion": str, "weight": "high|medium|low", "how_met": str, "evidence_ids": ["uuid"]} tied to analysis key_claims / catalog ids where possible
- options_matrix: list of objects {"option": str, "fit": str, "pros": [str], "cons": [str]} for structured comparison
- kill_criteria: list of strings — what would stop or reverse this recommendation
- what_would_change_our_mind: one short paragraph
- evidence_ledger_summary: one short paragraph summarizing how evidence supports the call

Your job is to synthesise everything into a final structured report that is:
- Clear and direct
- Professionally written
- Honest about limitations (especially unsupported or weak claims flagged by verification)
- Actionable

Output ONLY valid JSON:
{
  "recommendation": "One clear sentence",
  "confidence_level": "Low|Medium|Medium-High|High",
  "summary": "2-3 sentence executive summary (no new facts beyond linked claims)",
  "executive_insights": [{"text": "3-5 bullet-grade insights", "claim_ids": ["claim_id from analysis.key_claims"]}],
  "recommendation_claim_ids": ["claim_id", "..."],
  "key_risks_structured": [{"text": "Risk statement", "claim_ids": ["claim_id"]}],
  "key_reasons": ["Reason 1 with evidence", "Reason 2 with evidence"],
  "risks": ["Risk 1", "Risk 2"],
  "counterarguments": ["From critic, with response"],
  "next_steps": ["Step 1", "Step 2", "Step 3"],
  "sources": [{"title": "Source name", "type": "web|document|knowledge"}],
  "caveats": "Important limitations of this analysis",
  "decision_criteria": [{"criterion": "", "weight": "medium", "how_met": "", "evidence_ids": []}],
  "options_matrix": [{"option": "", "fit": "", "pros": [], "cons": []}],
  "kill_criteria": ["Condition that would invalidate this recommendation"],
  "what_would_change_our_mind": "New evidence or events that would shift the view",
  "evidence_ledger_summary": "How the evidence base supports the conclusion"
}

CLAIM LINKING: claim_ids in executive_insights, recommendation_claim_ids, and key_risks_structured MUST be
exactly the "claim_id" strings from analysis.key_claims (never invent). If analysis has key_claims, you must
fill recommendation_claim_ids (at least one) and executive_insights (at least one item).

QUALITY RULES (mandatory):
- recommendation must be ONE specific, actionable sentence ("Do X first because Y"), not "consider X".
- summary must include at least one specific number or timeframe drawn from linked claims / evidence.
- key_reasons: each item should imply what, why it matters, and what supports it (without inventing new facts).
- next_steps must be time-bound where possible ("Within 30 days: ...", "Within 90 days: ...").
- what_would_change_our_mind must name concrete thresholds or observations that would flip the call.
- evidence_ledger_summary must name the strongest 2–3 sources by title (from analysis / research only).

FORBIDDEN in the recommendation sentence: vague hedges ("might", "perhaps", "consider") as the main verb.
"""


class WriterAgent:
    async def run(
        self,
        query: str,
        analysis: dict,
        critique: dict,
        research: dict,
        prior_analysis: dict | None = None,
        verification: dict | None = None,
        *,
        reasoning_graph: dict | None = None,
        claim_support: list[dict] | None = None,
        repair_hint: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> WriterReportPayload:
        prior = ""
        if prior_analysis is not None:
            prior = f"""
First analyst draft (superseded by revision): {json.dumps(prior_analysis, indent=2)[:4000]}
"""
        ver = json.dumps(verification or {}, indent=2)[:6000]
        rg = json.dumps(reasoning_graph or {}, indent=2)[:6000]
        cs = json.dumps(claim_support or [], indent=2)[:6000]
        user_msg = f"""
Original query: {query}
Structured reasoning graph (canonical structure — align narrative to this): {rg}
Claim–support table (evidence vs assumption vs inference; use for honesty): {cs}
Revised analysis (use this as the primary analytical position): {json.dumps(analysis, indent=2)}
Critique: {json.dumps(critique, indent=2)}
Verifier output: {ver}
Research summary: {json.dumps(research, indent=2)[:2500]}
{prior}
In key_reasons and counterarguments, reflect verification verdicts (supported / weak / unsupported / overstates).
Split tone using claim_support support_type where helpful (direct_quote vs paraphrase vs inference vs assumption).
Respect nli_label / entailment fields in claim_support when present (contradicts / insufficient → flag honestly).
"""
        if repair_hint:
            user_msg += f"\n\nREPAIR REQUIRED:\n{repair_hint}\n"
        out, _meta = await generate_structured(
            WriterReportPayload,
            task_kind="writer",
            system=WRITER_SYSTEM,
            user=user_msg,
            temperature=0.3,
            session_id=session_id,
            trace_id=trace_id,
        )
        return out
