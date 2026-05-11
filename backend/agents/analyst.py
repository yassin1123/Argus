import json
import uuid
from typing import TYPE_CHECKING, Any

from core.inference.structured import generate_structured
from core.reasoning_skeleton import skeleton_hint_for_prompt
from models.agent_structured import AnalystStructuredOutput
from models.evidence import EvidenceObject

if TYPE_CHECKING:
    from core.consulting_modes import ResolvedConsultingMode  # noqa: F401


def _gen_kwargs_for_task(
    resolved_mode: "ResolvedConsultingMode | None",
    task_kind: str,
) -> dict[str, object]:
    """Read ``model_overrides[task_kind]`` off ``resolved_mode`` (W7
    iterate-4 plumbing). Mirrors the writer's reader; same shape so a
    later refactor can hoist this onto ``ResolvedConsultingMode``
    itself without changing call-site code."""
    if resolved_mode is None:
        return {}
    overrides = (resolved_mode.model_overrides or {}).get(task_kind) or {}
    out: dict[str, object] = {}
    mt = overrides.get("max_tokens")
    if isinstance(mt, int) and mt > 0:
        out["max_tokens"] = mt
    mo = overrides.get("model")
    if isinstance(mo, str) and mo.strip():
        out["model_override"] = mo.strip()
    return out

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

RECOMMENDATION QUALITY (this is what makes the report useful, not generic):
- The `recommendation` field must name a SPECIFIC course of action: which option, which segment, which sequence, which timeline.
  Bad:  "Pursue a phased approach to expansion."
  Good: "Run a 6-month Mittelstand pilot in NRW + Bavaria before committing France build-out."
- Reference at least one number/timeframe drawn from key_claims in the recommendation sentence.
- `core_reasoning` must explain WHY this specific path beats the alternatives, citing the strongest 2-3 claim_ids by reference.
- `key_reasons` must each start with a specific finding ("Concentrates 41% of...", "Cuts cycle by 2.4 months..."), not generic praise of an option.
- `assumptions` should name what would have to be true for the recommendation to hold (e.g. "Mittelstand procurement cycles do not lengthen materially in 2025").
- IMPORTANT: `assumptions` is a list of plain strings. Do NOT wrap each in an object — emit `["string 1", "string 2"]`, not `[{"assumption": "string 1"}, ...]`.

FORBIDDEN:
- Never argue "lack of evidence for X therefore choose Y" as the sole logic.
- Never produce fewer than 6 key_claims when the catalog + appendix together have at least 4 distinct sources/snippets.
- Never leave trade_offs empty for comparative decisions.
- Never use the phrases "phased approach", "balanced strategy", "leverage synergies", "best practices" — they signal you haven't picked.
- Never write a recommendation that could appear unchanged in a different industry's report.

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


def _rewrite_slot_claim_ids(analysis: dict[str, Any]) -> None:
    """W8/D5 follow-up: rewrite ``reasoning_slots[].claim_ids`` to point
    at real minted ``key_claims`` ids after ``_assign_claim_ids`` runs.

    The LLM emits ``reasoning_slots[].claim_ids`` referencing
    hallucinated tokens like ``claim_013`` because at emission time it
    has no real ids to anchor on. ``_assign_claim_ids`` then mints UUIDs
    on ``key_claims`` — leaving slot references dangling. The
    reasoning-skeleton gate (W6/D2) correctly rejects this, blocking
    growth_strategy memos from reaching the writer.

    Strategy:
      1. Collect actual minted claim_ids from key_claims.
      2. For each slot, keep any id that already matches a minted id.
      3. For each invalid id, try to recover by matching the slot's
         summary against the claim texts via word-overlap (threshold
         ≥3 shared words).
      4. Drop references that can't be recovered. If a slot ends up
         empty after recovery, leave it — the gate will then see a
         genuine coverage gap, not a referential one.
      5. Deduplicate the final list while preserving order.
    """
    kc = analysis.get("key_claims") or []
    if not isinstance(kc, list):
        return

    valid_ids: set[str] = set()
    id_to_text: dict[str, str] = {}
    for c in kc:
        if isinstance(c, dict) and c.get("claim_id"):
            cid = str(c["claim_id"])
            valid_ids.add(cid)
            id_to_text[cid] = str(c.get("text") or "")

    slots = analysis.get("reasoning_slots") or []
    if not isinstance(slots, list):
        return

    for slot in slots:
        if not isinstance(slot, dict):
            continue
        cids = slot.get("claim_ids") or []
        if not isinstance(cids, list):
            slot["claim_ids"] = []
            continue

        rewritten: list[str] = []
        slot_summary = str(slot.get("summary") or "").lower()
        slot_words = set(slot_summary.split())
        for cid in cids:
            cid_str = str(cid)
            if cid_str in valid_ids:
                rewritten.append(cid_str)
                continue
            # Hallucinated id — recover by matching slot summary text
            # against claim texts. Pick the claim with the most word
            # overlap; threshold ≥3 keeps recovery anchored to real
            # semantic overlap, not noise.
            best_id, best_overlap = None, 0
            for vid in valid_ids:
                claim_words = set(id_to_text[vid].lower().split())
                overlap = len(slot_words & claim_words)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_id = vid
            if best_id and best_overlap >= 3:
                rewritten.append(best_id)
            # else: silently drop; gate will see the coverage gap.

        # Deduplicate while preserving order.
        seen: set[str] = set()
        slot["claim_ids"] = [x for x in rewritten if not (x in seen or seen.add(x))]


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
        resolved_mode: "ResolvedConsultingMode | None" = None,
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
            **_gen_kwargs_for_task(resolved_mode, "analyst"),
        )
        data = out.model_dump()
        _sanitize_evidence_ids(data, allowed)
        _strip_ungrounded_key_claims(data)
        _assign_claim_ids(data)
        _rewrite_slot_claim_ids(data)  # W8/D5: rewrite slot refs to minted ids
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
        resolved_mode: "ResolvedConsultingMode | None" = None,
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
            **_gen_kwargs_for_task(resolved_mode, "analyst"),
        )
        data = out.model_dump()
        _sanitize_evidence_ids(data, allowed)
        _strip_ungrounded_key_claims(data)
        _assign_claim_ids(data)
        _rewrite_slot_claim_ids(data)  # W8/D5: rewrite slot refs to minted ids
        return data
