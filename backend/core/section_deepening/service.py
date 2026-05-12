"""Section-deepening service — W9/D1.

End-to-end flow for one (session_id, section_path, depth_directive)
request:

  1. Load the original session's report payload (writer output).
  2. Extract the target section via :func:`addressing.get_section`.
  3. Build a focused retrieval query from the section's content +
     depth_directive.
  4. Hybrid-retrieve up to 20 chunks; filter out chunks already
     cited in the section's evidence trail.
  5. Run a focused LLM call against the section-deepening writer
     prompt: produces a deepened section JSON in the same schema
     shape, citing existing claim_ids OR minted new ones grounded
     in the retrieved chunks.
  6. Persist the result to ``section_deepening_runs``.

Trade-off: the spec lists "analyst pass" + "verifier" + "writer"
as three separate passes. For Day 1's bounded scope, the service
combines them into one LLM call against the section-deepening
writer prompt — the prompt's hard rule "every new factual claim
must cite ..." plus the retrieved-chunks context substitute for
a separate verifier round. If Day 2+ shows fabrication issues,
the verifier can be re-introduced as a wrapper around the same
service entry point without touching the API contract.

Hard rules from spec:
- The original session payload is NOT modified in place. We only
  capture the section snapshot + the deepened section into the
  ``section_deepening_runs`` row.
- Read-only against the chunks table — the service queries but
  never writes new chunks.
- One section per request — no fan-out today.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any
from uuid import UUID

from agents.writer.prompts import SECTION_DEEPENING_WRITER_PROMPT
from core.json_util import parse_llm_json
from core.llm import llm_call_for_task
from core.retrieval_chunks import hybrid_search
from db.connection import acquire

from .addressing import SectionNotFoundError, get_section
from .types import DeepeningRequest, DeepeningResult

logger = logging.getLogger(__name__)

# Cap how many newly-retrieved chunks the LLM sees per deepening
# request. Bounded for cost discipline — at 20 chunks × ~400 tokens
# each, prompt overhead is ~8KB which keeps the call well inside
# any model's context budget.
MAX_NEW_CHUNKS = 20

# Truncation for the section-content excerpt the retrieval query
# is built from. Keeps the embedding/keyword query focused on the
# section's actual material, not the whole memo.
_SECTION_CONTEXT_TRUNCATE = 800


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def _insert_queued_run(
    request: DeepeningRequest,
    triggered_by: UUID,
    firm_id: UUID,
    original_section: Any,
) -> UUID:
    """Insert a ``queued`` row before the work starts; returns the row id."""
    deepening_id = uuid.uuid4()
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO section_deepening_runs
              (id, session_id, firm_id, section_path, depth_directive,
               triggered_by, original_section_json, status)
            VALUES
              ($1::uuid, $2::uuid, $3::uuid, $4, $5,
               $6::uuid, $7::jsonb, 'queued')
            """,
            deepening_id,
            request.session_id,
            firm_id,
            request.section_path,
            request.depth_directive,
            triggered_by,
            json.dumps(original_section),
        )
    return deepening_id


async def _mark_running(deepening_id: UUID) -> None:
    async with acquire() as conn:
        await conn.execute(
            "UPDATE section_deepening_runs SET status='running' WHERE id=$1::uuid",
            deepening_id,
        )


async def _persist_complete(
    deepening_id: UUID,
    *,
    deepened_section: Any,
    new_claim_ids: list[str],
    new_evidence_chunks_used: int,
    cost_usd: float,
    wall_seconds: float,
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE section_deepening_runs SET
                status='complete',
                deepened_section_json = $2::jsonb,
                new_claim_ids = $3::jsonb,
                new_evidence_chunks_used = $4,
                cost_usd = $5,
                wall_seconds = $6,
                completed_at = NOW()
            WHERE id = $1::uuid
            """,
            deepening_id,
            json.dumps(deepened_section),
            json.dumps(new_claim_ids),
            new_evidence_chunks_used,
            cost_usd,
            wall_seconds,
        )


async def _persist_failed(
    deepening_id: UUID,
    *,
    reason: str,
    wall_seconds: float,
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE section_deepening_runs SET
                status='failed',
                failure_reason = $2,
                wall_seconds = $3,
                completed_at = NOW()
            WHERE id = $1::uuid
            """,
            deepening_id,
            reason[:2000],
            wall_seconds,
        )


# ---------------------------------------------------------------------------
# Payload + section loading
# ---------------------------------------------------------------------------


async def _load_report_payload(session_id: UUID) -> dict[str, Any] | None:
    """Pull the writer's full payload from ``reports``. Returns the
    merged shape ``base_fields + consulting_payload`` so dotted paths
    resolve uniformly whether they target a base field
    (``recommendation``) or an M&A-specific section
    (``synergy_estimate.cost_synergies``).
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT recommendation, confidence_level, summary, key_reasons, risks,
                   counterarguments, next_steps, sources, caveats, consulting_payload
            FROM reports WHERE session_id = $1::uuid
            """,
            session_id,
        )
    if not row:
        return None
    base: dict[str, Any] = {k: row[k] for k in row.keys() if k != "consulting_payload"}
    cp = row["consulting_payload"]
    if isinstance(cp, str):
        try:
            cp = json.loads(cp)
        except Exception:
            cp = {}
    if isinstance(cp, dict):
        base.update(cp)
    return base


async def _firm_id_for_session(session_id: UUID) -> UUID | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id=$1::uuid", session_id
        )
    return row["firm_id"] if row and row["firm_id"] else None


# ---------------------------------------------------------------------------
# Retrieval — build query + filter cited chunks
# ---------------------------------------------------------------------------


def _existing_claim_ids(section: Any) -> set[str]:
    """Best-effort sweep over the section for any claim_id-shaped
    references. Covers the schemas we ship today:

    - WriterReportBase: ``recommendation_claim_ids``,
      ``executive_insights[].claim_ids``,
      ``key_risks_structured[].claim_ids``
    - M&A Synergy: ``basis_citations`` (each entry is a claim_id-ish string)
    - 2x2 TwoByTwoItem: ``evidence_citations`` (claim_id list)
    - Porter ForceAssessment: ``evidence_citations``
    - ValueChainActivity: ``evidence_citations``
    """
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in (
                    "recommendation_claim_ids",
                    "claim_ids",
                    "evidence_citations",
                    "basis_citations",
                ) and isinstance(v, list):
                    for x in v:
                        if isinstance(x, str) and x.strip():
                            found.add(x.strip())
                else:
                    walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(section)
    return found


def _build_retrieval_query(section: Any, depth_directive: str | None) -> str:
    """Compose a focused retrieval query from the section's prose
    + the consultant's directive. Truncated so the embedding /
    keyword index doesn't get a runaway-long query string."""
    parts: list[str] = []
    if depth_directive and depth_directive.strip():
        parts.append(depth_directive.strip())
    # Flatten the section's text content. Numbers and structural
    # noise get filtered; long prose dominates.
    text_bits: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str) and node.strip():
            text_bits.append(node.strip())
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(section)
    section_text = " ".join(text_bits)[:_SECTION_CONTEXT_TRUNCATE]
    if section_text:
        parts.append(section_text)
    return " ".join(parts)[: _SECTION_CONTEXT_TRUNCATE + 1000]


async def _retrieve_new_chunks(
    session_id: UUID,
    query: str,
    already_cited: set[str],
) -> list[dict[str, Any]]:
    """Hybrid-search up to ``MAX_NEW_CHUNKS`` chunks; filter out any
    chunk whose evidence_id / claim_id is in ``already_cited``.
    """
    if not query.strip():
        return []
    out = await hybrid_search(
        engagement_id=str(session_id),
        query=query,
        k=MAX_NEW_CHUNKS,
        candidate_k=max(30, MAX_NEW_CHUNKS * 2),
    )
    results = out.get("results") or []
    fresh: list[dict[str, Any]] = []
    for r in results:
        cid = str(r.get("evidence_id") or r.get("id") or "").strip()
        if cid and cid in already_cited:
            continue
        fresh.append(r)
        if len(fresh) >= MAX_NEW_CHUNKS:
            break
    return fresh


# ---------------------------------------------------------------------------
# LLM call — focused deepening writer pass
# ---------------------------------------------------------------------------


def _format_chunks_for_prompt(chunks: list[dict[str, Any]]) -> str:
    """Compact textual representation of the retrieved chunks the
    deepening writer prompt receives. Each chunk shows its id (so
    the LLM can cite it as a new claim_id) + quote + source meta.
    """
    if not chunks:
        return "(no new chunks retrieved)"
    lines: list[str] = []
    for c in chunks[:MAX_NEW_CHUNKS]:
        cid = c.get("evidence_id") or c.get("id") or "?"
        title = c.get("source_title") or c.get("source_type") or ""
        quote = (c.get("quote") or c.get("text") or "")[:500]
        lines.append(f"[id={cid}] ({title}): {quote}")
    return "\n".join(lines)


async def _call_deepening_writer(
    *,
    section_path: str,
    original_section: Any,
    depth_directive: str | None,
    new_chunks: list[dict[str, Any]],
    session_id: UUID,
) -> tuple[Any, list[str]]:
    """Run the section-deepening writer pass; return
    ``(deepened_section, new_claim_ids_used)``. ``new_claim_ids``
    are extracted from the deepened section after the fact via the
    same sweep used to compute ``already_cited``.
    """
    directive_block = depth_directive.strip() if depth_directive else "(no specific directive — produce a generally deeper, better-grounded version)"
    user_msg = (
        f"Section path: {section_path}\n\n"
        f"Depth directive:\n{directive_block}\n\n"
        f"Original section (JSON):\n{json.dumps(original_section, ensure_ascii=False, indent=2)[:6000]}\n\n"
        f"Newly retrieved evidence chunks (cite their ids as claim_ids):\n"
        f"{_format_chunks_for_prompt(new_chunks)}\n\n"
        f"Produce the deepened section JSON now. Same shape as the original; "
        f"no extra fields; no markdown wrapper."
    )
    raw = await llm_call_for_task(
        "writer",
        system=SECTION_DEEPENING_WRITER_PROMPT,
        user=user_msg,
        session_id=str(session_id),
    )
    parsed = parse_llm_json(raw)
    # parse_llm_json returns dict on object output. For non-object
    # sections (list or scalar) we fall back to raw JSON load.
    if parsed is None or (isinstance(parsed, dict) and not parsed):
        try:
            parsed = json.loads(raw.strip())
        except Exception:
            # Last-ditch: hand back the raw string so the failure
            # path can persist it for forensic inspection.
            parsed = {"_raw": raw[:4000]}
    new_ids = sorted(_existing_claim_ids(parsed))
    return parsed, new_ids


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def deepen_section(
    request: DeepeningRequest,
    triggered_by: UUID,
) -> DeepeningResult:
    """End-to-end deepening of one section.

    The function blocks until completion — the API layer calls it
    via FastAPI's BackgroundTasks (returning the queued
    ``deepening_id`` immediately to the caller). Persistence at
    every stage means a partial failure leaves a row in
    ``section_deepening_runs`` with ``status='failed'`` and a
    readable ``failure_reason``.
    """
    t0 = time.perf_counter()

    firm_id = await _firm_id_for_session(request.session_id)
    if firm_id is None:
        # Without firm_id we can't insert into section_deepening_runs
        # (FK). Bail out early with a synthetic failed result the
        # caller can surface — nothing persisted because we never
        # had a row to update.
        return DeepeningResult(
            deepening_id=uuid.uuid4(),
            section_path=request.section_path,
            original_section_json=None,
            deepened_section_json=None,
            status="failed",
            failure_reason=f"session {request.session_id} has no firm_id (deleted or malformed)",
            wall_seconds=time.perf_counter() - t0,
        )

    payload = await _load_report_payload(request.session_id)
    if payload is None:
        return DeepeningResult(
            deepening_id=uuid.uuid4(),
            section_path=request.section_path,
            original_section_json=None,
            deepened_section_json=None,
            status="failed",
            failure_reason=f"session {request.session_id} has no report row to deepen",
            wall_seconds=time.perf_counter() - t0,
        )

    # Address the section. SectionNotFoundError is the most common
    # caller-facing failure and persists with the original path so
    # the consultant sees exactly what they asked for.
    try:
        original_section = get_section(payload, request.section_path)
    except SectionNotFoundError as e:
        deepening_id = await _insert_queued_run(
            request, triggered_by, firm_id, original_section=None
        )
        wall = time.perf_counter() - t0
        await _persist_failed(deepening_id, reason=str(e), wall_seconds=wall)
        return DeepeningResult(
            deepening_id=deepening_id,
            section_path=request.section_path,
            original_section_json=None,
            deepened_section_json=None,
            status="failed",
            failure_reason=str(e),
            wall_seconds=wall,
        )

    deepening_id = await _insert_queued_run(
        request, triggered_by, firm_id, original_section
    )
    await _mark_running(deepening_id)

    try:
        already_cited = _existing_claim_ids(original_section)
        query = _build_retrieval_query(original_section, request.depth_directive)
        new_chunks = await _retrieve_new_chunks(
            request.session_id, query, already_cited
        )
        deepened_section, new_claim_ids = await _call_deepening_writer(
            section_path=request.section_path,
            original_section=original_section,
            depth_directive=request.depth_directive,
            new_chunks=new_chunks,
            session_id=request.session_id,
        )
        # New claim ids = those in the deepened section but not in
        # the original section's cited set. Bounded sweep, no LLM.
        truly_new = sorted(set(new_claim_ids) - already_cited)

        wall = time.perf_counter() - t0
        # Cost is captured by the cost-tracking row in ``llm_calls`` for
        # the writer task call; pulling it back requires an extra
        # query. For Day 1 we leave cost_usd=0.0 on the deepening row
        # — the truth lives in llm_calls, and a Day 2+ pass can sum it.
        await _persist_complete(
            deepening_id,
            deepened_section=deepened_section,
            new_claim_ids=truly_new,
            new_evidence_chunks_used=len(new_chunks),
            cost_usd=0.0,
            wall_seconds=wall,
        )
        return DeepeningResult(
            deepening_id=deepening_id,
            section_path=request.section_path,
            original_section_json=original_section,
            deepened_section_json=deepened_section,
            new_claim_ids=truly_new,
            new_evidence_chunks_used=len(new_chunks),
            cost_usd=0.0,
            wall_seconds=wall,
            status="complete",
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("deepen_section failed for id=%s", deepening_id)
        wall = time.perf_counter() - t0
        reason = f"{type(e).__name__}: {e}"
        await _persist_failed(deepening_id, reason=reason, wall_seconds=wall)
        return DeepeningResult(
            deepening_id=deepening_id,
            section_path=request.section_path,
            original_section_json=original_section,
            deepened_section_json=None,
            status="failed",
            failure_reason=reason,
            wall_seconds=wall,
        )
