import json
import uuid
from typing import Any

from core.inference.structured import generate_structured
from core.reasoning_skeleton import skeleton_hint_for_prompt
from models.agent_structured import AnalystStructuredOutput
from models.evidence import EvidenceObject

ANALYST_SYSTEM = """
You are the Analyst agent in the Argus decision system.
You receive a research plan, research findings, and a catalog of evidence objects (persistent UUID ids).

SYNTHESIS RULES (mandatory):
- Produce at least 6 key_claims whenever the evidence base allows; if you have fewer, you are being too conservative.
- For each web-oriented item in the Web evidence appendix, extract the most specific quantitative claim you can (ranges, timeframes, %).
- Paraphrase is allowed when tied to catalog evidence_ids; cite the evidence_object UUIDs that best support each claim.
- For comparative questions (A vs B), produce claims for BOTH options; never recommend against an option solely because you have fewer citations for it.
- Quantify where possible using numbers, percentages, and timeframes from the catalog and appendix.
- If evidence is weak, say so in the claim text, e.g. "Evidence suggests (limited data) ...".
- trade_offs MUST cover both main options with at least 3 pros and 3 cons each when the query compares options.

FORBIDDEN:
- Never argue "lack of evidence for X therefore choose Y" as the sole logic.
- Never produce fewer than 6 key_claims when the catalog + appendix together have at least 4 distinct sources/snippets.
- Never leave trade_offs empty for comparative decisions.

Rules:
1. Every substantive point must cite evidence_object ids from the catalog in "key_claims".
2. key_claims is a list of { "text": "claim", "evidence_ids": ["uuid", ...] } — ids MUST exist in the catalog.
3. Prefer document and web quotes from the catalog; do not invent ids.
4. Call out thin or conflicting evidence in evidence_strength.
5. Fill "reasoning_slots" as required by the consulting mode (see user message). Each slot ties narrative to key_claims via claim_ids.

Output ONLY valid JSON:
{
  "recommendation": "Clear recommendation statement",
  "confidence": "Low|Medium|Medium-High|High",
  "core_reasoning": "Main argument for recommendation",
  "key_reasons": ["Reason 1", "Reason 2", "Reason 3"],
  "key_claims": [{"claim_id": "(optional UUID)", "text": "Claim tied to evidence", "evidence_ids": ["uuid"]}],
  "reasoning_slots": [{"slot_id": "snake_case_id", "summary": "Insight for this dimension", "claim_ids": ["claim_uuid"]}],
  "trade_offs": [{"option": "X", "pros": ["..."], "cons": ["..."]}],
  "evidence_strength": "Assessment of overall evidence quality",
  "assumptions": ["Assumption 1", "Assumption 2"]
}
"""

ANALYST_REVISION_SYSTEM = """
You are the Analyst agent performing a REQUIRED revision pass in Argus.
You receive the original query, research, first analyst draft, critic review (including revision_instructions), and the evidence catalog.

Apply the same SYNTHESIS RULES as the first pass (≥6 key_claims when evidence allows, both sides for A vs B, rich trade_offs, no "lack of evidence for X ⇒ Y" shortcuts).

1. Address revision_instructions in order of severity (high first).
2. Every key_claims entry must cite only valid evidence ids from the catalog.
3. Output the SAME JSON schema as the first analyst pass (full replacement analysis), including reasoning_slots when required.

Output ONLY valid JSON:
{
  "recommendation": "Clear recommendation statement (possibly revised)",
  "confidence": "Low|Medium|Medium-High|High",
  "core_reasoning": "Main argument after revision",
  "key_reasons": ["Reason 1", "Reason 2", "Reason 3"],
  "key_claims": [{"claim_id": "(optional)", "text": "Claim", "evidence_ids": ["uuid"]}],
  "reasoning_slots": [{"slot_id": "snake_case_id", "summary": "Insight", "claim_ids": ["claim_uuid"]}],
  "trade_offs": [{"option": "X", "pros": ["..."], "cons": ["..."]}],
  "evidence_strength": "Assessment after critique",
  "assumptions": ["Assumption 1", "Assumption 2"]
}
"""


def _catalog_json(evidence_objects: list[EvidenceObject] | None) -> str:
    if not evidence_objects:
        return "[]"
    return json.dumps([o.for_llm_catalog() for o in evidence_objects if o.id], ensure_ascii=False)[:16000]


def _web_evidence_appendix(research: dict) -> str:
    """Flatten web_citations from research findings for analyst grounding (titles/URLs/snippets)."""
    lines: list[str] = []
    seen: set[str] = set()
    for f in research.get("findings") or []:
        if not isinstance(f, dict):
            continue
        for w in f.get("web_citations") or []:
            if not isinstance(w, dict):
                continue
            url = str(w.get("url") or "").strip()
            key = url or str(w.get("title") or "")
            if key in seen:
                continue
            seen.add(key)
            title = str(w.get("title") or "")[:200]
            snip = str(w.get("snippet") or "")[:400]
            if title or url:
                lines.append(f"- {title} | {url}\n  Snippet: {snip}")
    if not lines:
        return "(none)"
    return "\n".join(lines)[:8000]


def _sanitize_evidence_ids(analysis: dict[str, Any], allowed: set[str]) -> None:
    kc = analysis.get("key_claims")
    if not isinstance(kc, list):
        return
    for item in kc:
        if not isinstance(item, dict):
            continue
        raw = item.get("evidence_ids")
        if not isinstance(raw, list):
            item["evidence_ids"] = []
            continue
        item["evidence_ids"] = [str(x) for x in raw if str(x) in allowed]


def _strip_ungrounded_key_claims(analysis: dict[str, Any]) -> None:
    """Remove key_claims with empty evidence_ids after sanitization; keep audit trail."""
    kc = analysis.get("key_claims")
    if not isinstance(kc, list):
        return
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for item in kc:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        raw = item.get("evidence_ids")
        eids = [str(x) for x in raw] if isinstance(raw, list) else []
        if text and not eids:
            dropped.append(dict(item))
        else:
            kept.append(item)
    analysis["key_claims"] = kept
    if dropped:
        prev = analysis.get("ungrounded_candidates")
        if not isinstance(prev, list):
            prev = []
        analysis["ungrounded_candidates"] = prev + dropped


def _assign_claim_ids(analysis: dict[str, Any]) -> None:
    kc = analysis.get("key_claims")
    if not isinstance(kc, list):
        return
    for item in kc:
        if not isinstance(item, dict):
            continue
        if str(item.get("text", "")).strip() and not item.get("claim_id"):
            item["claim_id"] = str(uuid.uuid4())


class AnalystAgent:
    async def run(
        self,
        query: str,
        plan: dict,
        research: dict,
        evidence_objects: list[EvidenceObject] | None = None,
        *,
        report_mode: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        allowed = {str(o.id) for o in (evidence_objects or []) if o.id}
        skel = skeleton_hint_for_prompt((report_mode or "general").strip().lower())
        web_app = _web_evidence_appendix(research)
        user_msg = f"""
Original query: {query}
Research plan: {json.dumps(plan, indent=2)[:6000]}
Research findings: {json.dumps(research, indent=2)[:12000]}
Web evidence (use freely; cite by matching UUIDs in the catalog that correspond to these sources): 
{web_app}
Evidence object catalog (cite ids from here): {_catalog_json(evidence_objects)}
{skel}
"""
        out, _meta = await generate_structured(
            AnalystStructuredOutput,
            task_kind="analyst",
            system=ANALYST_SYSTEM,
            user=user_msg,
            session_id=session_id,
            trace_id=trace_id,
        )
        data = out.model_dump()
        _sanitize_evidence_ids(data, allowed)
        _strip_ungrounded_key_claims(data)
        _assign_claim_ids(data)
        return data

    async def revise(
        self,
        query: str,
        plan: dict,
        research: dict,
        analysis: dict,
        critique: dict,
        evidence_objects: list[EvidenceObject] | None = None,
        *,
        gate_feedback: list[str] | None = None,
        draft_label: str = "First analyst draft",
        report_mode: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict:
        allowed = {str(o.id) for o in (evidence_objects or []) if o.id}
        gate_block = ""
        if gate_feedback:
            gate_block = f"""
MANDATORY FIXES (address every line):
{chr(10).join(f"- {e}" for e in gate_feedback)}
"""
        skel = skeleton_hint_for_prompt((report_mode or "general").strip().lower())
        user_msg = f"""
Original query: {query}
Research plan: {json.dumps(plan, indent=2)[:6000]}
Research findings: {json.dumps(research, indent=2)[:10000]}
{draft_label}: {json.dumps(analysis, indent=2)[:8000]}
Critic review: {json.dumps(critique, indent=2)[:8000]}
Web evidence appendix:
{_web_evidence_appendix(research)}
Evidence object catalog: {_catalog_json(evidence_objects)}
{skel}
{gate_block}
Produce the revised analyst JSON only.
"""
        out, _meta = await generate_structured(
            AnalystStructuredOutput,
            task_kind="analyst",
            system=ANALYST_REVISION_SYSTEM,
            user=user_msg,
            session_id=session_id,
            trace_id=trace_id,
        )
        data = out.model_dump()
        _sanitize_evidence_ids(data, allowed)
        _strip_ungrounded_key_claims(data)
        _assign_claim_ids(data)
        return data
