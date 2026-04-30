"""Structured grounder — turns the writer's narrative into citation-grounded sections.

Runs after the writer. Given the writer payload + the engagement's chunks, asks
the LLM (via Instructor for forced structure) to produce a `StructuredAnswer`
where every claim references real chunk_ids from the catalog.

Validation pass: any chunk_id that's not in the engagement's chunk catalog is
dropped from the claim, and a note is appended to `validation_notes`. Claims
that lose all their chunks get their confidence downgraded to "contested".
"""

from __future__ import annotations

import logging
from typing import Any

import instructor
import litellm
from pydantic import ValidationError

from models.report import WriterReportPayload
from models.structured_answer import StructuredAnswer
from storage.chunk_queries import list_chunks_for_session

logger = logging.getLogger(__name__)


GROUNDER_SYSTEM = """You are the Structured Grounder for Argus, a consulting AI workbench.

You receive a finished writer-grade report (a recommendation memo) and a catalog
of CHUNKS from the engagement's source library. Your job is to re-express the
report as a `StructuredAnswer` where:

1. `tldr` is one or two sentences — the headline answer.
2. `sections` mirror the writer's executive insights and key risks, one section
   per coherent narrative beat. Each section has `heading`, `text`, `claims`.
3. Every `claim` MUST reference 1-3 `chunk_ids` from the catalog whose content
   actually supports the claim. NEVER reference an id not in the catalog.
4. `confidence` per claim:
   - "high"      → multiple chunks corroborate, all firm/credible-tier
   - "medium"    → single chunk, OR mostly web-tier, OR partial coverage
   - "contested" → no chunk in the catalog clearly supports → still emit the claim with empty chunk_ids and note why
5. `caveats` carries any unsupported claims, missing-source notes, or staleness flags.

Rules:
- Do NOT invent claims that weren't in the input report.
- Do NOT reference chunks that aren't in the catalog.
- If you can't find supporting chunks, set chunk_ids = [] and confidence = "contested".
- `text` of each claim should be a single specific sentence drawn from the report.
"""


def _catalog_for_prompt(chunks: list[dict[str, Any]], max_chars: int = 14000) -> tuple[str, set[str]]:
    """Render the chunk catalog as a compact list. Returns (rendered, valid_ids_set)."""
    valid: set[str] = set()
    lines: list[str] = []
    used = 0
    for c in chunks:
        cid = str(c.get("id") or "")
        if not cid:
            continue
        snippet = (c.get("content") or "").strip().replace("\n", " ")[:240]
        page = c.get("page")
        section = c.get("section_heading")
        kind = c.get("source_type") or "src"
        loc = []
        if page:
            loc.append(f"p.{page}")
        if section:
            loc.append(f"§ {section}"[:60])
        loc_str = " · ".join(loc)
        line = f"[{cid}] ({kind}{' · ' + loc_str if loc_str else ''}) {snippet}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        valid.add(cid)
        used += len(line) + 1
    return "\n".join(lines), valid


def _writer_brief(payload: WriterReportPayload) -> str:
    """Compact textual brief of the writer payload for the grounder."""
    cp_dict = payload.consulting_payload_dict()
    insights = "\n".join(f"- {x.get('text','')}" for x in cp_dict.get("executive_insights", []))
    risks = "\n".join(f"- {x.get('text','')}" for x in cp_dict.get("key_risks_structured", []))
    next_steps = "\n".join(f"- {s}" for s in payload.next_steps[:8])
    return (
        f"RECOMMENDATION:\n{payload.recommendation}\n\n"
        f"SUMMARY:\n{payload.summary}\n\n"
        f"EXECUTIVE INSIGHTS:\n{insights or '(none)'}\n\n"
        f"KEY RISKS:\n{risks or '(none)'}\n\n"
        f"NEXT STEPS:\n{next_steps or '(none)'}\n\n"
        f"CAVEATS:\n{payload.caveats or '(none)'}"
    )


def _validate(answer: StructuredAnswer, valid_ids: set[str]) -> StructuredAnswer:
    """Drop unknown chunk_ids; downgrade claims that lose all their support."""
    notes: list[str] = list(answer.validation_notes)
    dropped_total = 0
    downgraded_total = 0
    for s in answer.sections:
        for claim in s.claims:
            kept: list[str] = []
            for cid in claim.chunk_ids:
                if cid in valid_ids:
                    kept.append(cid)
                else:
                    dropped_total += 1
            if len(kept) != len(claim.chunk_ids):
                claim.chunk_ids = kept
            if not kept and claim.confidence != "contested":
                claim.confidence = "contested"
                downgraded_total += 1
    if dropped_total:
        notes.append(f"Dropped {dropped_total} fabricated chunk_id reference(s).")
    if downgraded_total:
        notes.append(f"Downgraded {downgraded_total} claim(s) to 'contested' (no valid chunks).")
    answer.validation_notes = notes
    return answer


async def ground_writer_payload(
    *,
    session_id: str,
    payload: WriterReportPayload,
    model: str = "gpt-4o-mini",
    timeout_seconds: float = 60.0,
) -> StructuredAnswer:
    """Run the grounder. Returns a validated `StructuredAnswer`.

    On failure, returns a minimal answer derived from the payload alone (no chunk refs).
    """
    chunks = await list_chunks_for_session(session_id, limit=80)
    if not chunks:
        # No chunks yet — return a degenerate StructuredAnswer with the writer text.
        sec_texts: list[str] = [payload.summary]
        for ins in payload.consulting_payload_dict().get("executive_insights", []):
            t = (ins.get("text") or "").strip()
            if t:
                sec_texts.append(t)
        return StructuredAnswer(
            tldr=payload.recommendation[:300],
            sections=[
                {"heading": "", "text": t, "claims": []} for t in sec_texts if t
            ],
            caveats=payload.caveats or "",
            validation_notes=["No chunks in engagement; structured answer ungrounded."],
        )

    catalog, valid_ids = _catalog_for_prompt(chunks)
    brief = _writer_brief(payload)
    user_msg = (
        f"Writer report:\n\n{brief}\n\n"
        f"Available chunk catalog (use only these ids):\n\n{catalog}"
    )

    # Instructor wrapping LiteLLM. Forces typed StructuredAnswer output.
    try:
        client = instructor.from_litellm(litellm.acompletion)
        result = await client.chat.completions.create(
            model=model,
            response_model=StructuredAnswer,
            timeout=timeout_seconds,
            messages=[
                {"role": "system", "content": GROUNDER_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_retries=1,
        )
    except (ValidationError, Exception) as e:  # noqa: BLE001
        logger.warning("structured_grounder failed: %s", e)
        return StructuredAnswer(
            tldr=payload.recommendation[:300],
            sections=[],
            caveats=payload.caveats or "",
            validation_notes=[f"Grounder error: {type(e).__name__}"],
        )

    return _validate(result, valid_ids)
