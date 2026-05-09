"""Writer agent. Phase 2 / Week 7 / Day 1: pulled out of the
single-file ``agents/writer.py`` so the schema registry can live
alongside it (``agents/writer/schemas/``).

The runtime behaviour of ``WriterAgent.run`` is unchanged from the
W6 implementation. Schema selection happens via the registry lookup;
``GeneralReportPayload`` is the default and matches what every
existing built-in mode produces today.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.inference.structured import generate_structured

from .schemas import GeneralReportPayload, WriterReportBase, get_writer_schema

if TYPE_CHECKING:
    from core.consulting_modes import ResolvedConsultingMode  # noqa: F401

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

QUALITY RULES (mandatory — these are the difference between consultant-speak and a usable plan):

RECOMMENDATION:
- ONE specific sentence naming the option chosen (e.g. "Enter Germany first via a 6-month Mittelstand pilot in NRW + Bavaria" — NOT "Pursue a phased approach").
- Must reference at least one specific entity: country, segment, channel, vendor, dollar amount, or timeline drawn from linked claims.
- Must answer "what to do," not "what to consider."

SUMMARY (2-4 sentences):
- Sentence 1: the recommendation, sharper than the headline.
- Sentence 2: the single biggest reason supported by evidence (cite a number).
- Sentence 3: the single biggest risk and the gate that mitigates it.
- Optional sentence 4: what to do this week.

KEY_REASONS (4-7 items):
- Each starts with a verb-of-finding ("Concentrates 41% of...", "Cuts procurement cycle by 2.4 months...").
- Each names a specific number, ratio, threshold, or timeframe from the evidence.
- Avoid generic phrases like "the market is large" — replace with the actual size.

NEXT_STEPS (5-9 items, this is the Action Plan):
- Each step MUST start with a time-bound prefix: "This week:", "Within 30 days:", "Within 90 days:", "By month 6:", etc.
- Each step MUST name an action verb ("Recruit", "Sign", "Stand up", "Run", "Validate", "Negotiate", "Decommission") — not "explore" or "consider."
- Each step SHOULD name a measurable output: a number of accounts, a signed document, a launched feature, a dashboard, a hire.
- Include at least one "kill check" step that ties back to kill_criteria (e.g. "Month 5: review 6-anchor pipeline; if 0 LOIs, kill phase-2 plan.").
- The first 2 steps should be doable this week with the team that exists.

DECISION_CRITERIA (4-8):
- Use weight high|medium|low to differentiate; not all "high".
- "how_met" must reference an evidence id or a specific number, not paraphrase.

OPTIONS_MATRIX (2-4):
- "fit" should be a one-line verdict, not a paragraph (e.g. "Best at this team size; longer cycles." or "Faster TAM growth, harder to capture at 12 HC.").
- 3-5 pros and 3-5 cons each, each pro/con is one phrase or sentence.
- Always include a "do nothing / status quo" option if defensible.

KILL_CRITERIA (3-6):
- Each starts "If <observable> by <timepoint>, then <action>." (e.g. "If 0 of 6 anchors move to LOI by month 5, halt build-out and re-plan.")
- These are the bright lines that make this plan falsifiable.

WHAT_WOULD_CHANGE_OUR_MIND:
- Name concrete thresholds or observations: "Direct evidence that French procurement cycles exceed German cycles in our verticals", not "more data".

EVIDENCE_LEDGER_SUMMARY:
- Name the 2-3 strongest source titles. State sample sizes (n=) where the evidence is empirical.
- State the weakest claim explicitly (verifier-flagged) with its claim_id.

FORBIDDEN in any field — these phrases mark a generic LLM answer, not a real plan:
- "phased approach", "leverage synergies", "best practices", "explore opportunities"
- "consider", "perhaps", "might want to" — as the main verb of recommendation or next_steps
- Any sentence that could appear unchanged in a different industry's report.

If the analysis lacks the specifics to meet these rules, populate the field with the best available specifics and flag the gap in caveats. Don't pad with generic prose.
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
        resolved_mode: "ResolvedConsultingMode | None" = None,
    ) -> WriterReportBase:
        prior = ""
        if prior_analysis is not None:
            prior = f"""
First analyst draft (superseded by revision): {json.dumps(prior_analysis, indent=2)[:4000]}
"""
        ver = json.dumps(verification or {}, indent=2)[:6000]
        rg = json.dumps(reasoning_graph or {}, indent=2)[:6000]
        cs = json.dumps(claim_support or [], indent=2)[:6000]

        # Mode header surfaces display_name + description so the LLM
        # knows what kind of memo to write under (and the cover/header
        # references the firm-overridden label when one exists).
        mode_header = ""
        if resolved_mode is not None:
            mh_parts: list[str] = [
                f"Consulting mode: {resolved_mode.display_name} "
                f"(slug: {resolved_mode.name})"
            ]
            if (resolved_mode.description or "").strip():
                mh_parts.append(f"Mode description: {resolved_mode.description.strip()}")
            mode_header = "\n".join(mh_parts) + "\n\n"

        user_msg = f"""
{mode_header}Original query: {query}
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

        system_prompt = WRITER_SYSTEM
        if resolved_mode is not None and (resolved_mode.writer_overlay or "").strip():
            system_prompt = (
                WRITER_SYSTEM
                + "\n\nFIRM WRITER OVERLAY:\n"
                + resolved_mode.writer_overlay.strip()
            )

        # W7/D1: registry-driven schema selection. Built-in modes still
        # validate against GeneralReportPayload; m_and_a_diligence (and
        # whatever Phase 3 adds) gets its bespoke class. Day 2 will
        # build the per-mode prompt — today the prompt stays generic
        # and the writer just routes to the right validator.
        schema_cls: type[WriterReportBase] = GeneralReportPayload
        if resolved_mode is not None:
            schema_cls = get_writer_schema(resolved_mode.name)

        out, _meta = await generate_structured(
            schema_cls,
            task_kind="writer",
            system=system_prompt,
            user=user_msg,
            temperature=0.3,
            session_id=session_id,
            trace_id=trace_id,
        )
        return out
