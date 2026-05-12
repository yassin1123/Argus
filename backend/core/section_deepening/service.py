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
from agents.writer.schemas import GeneralReportPayload, get_writer_schema
from core.consulting_modes import ResolvedConsultingMode, resolve_mode
from core.json_util import parse_llm_json
from core.llm import llm_call_for_task
from core.retrieval_chunks import hybrid_search
from db.connection import acquire

from .addressing import SectionNotFoundError, get_section
from .types import DeepeningRequest, DeepeningResult
from .validation import SchemaPathError, validate_section_against_schema

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

# W9/D4: per-deepening cost ceiling. Bounded cost is part of the
# trust contract with firms — exceeding this aborts pre-firing
# with ``failure_reason='exceeded_per_run_cost_cap'``. Don't raise
# without a real-world reason. Cost estimation uses a coarse
# heuristic over the prompt-token volume + retrieved-chunk volume
# (see ``_estimate_call_cost_usd``).
MAX_DEEPENING_COST_USD = 0.75

# Coarse pricing assumption used for the pre-flight estimate.
# Real cost lands on the ``llm_calls`` row after the call; this
# guard rail just refuses to fire obviously-over-budget requests.
# Tuned against ``writer`` task config in models.yaml; treat as
# an upper bound (OpenAI gpt-4o pricing as of 2025).
_ESTIMATED_PROMPT_USD_PER_TOKEN = 5.0 / 1_000_000   # $5 / 1M input tokens
_ESTIMATED_OUTPUT_USD_PER_TOKEN = 15.0 / 1_000_000  # $15 / 1M output tokens
_CHARS_PER_TOKEN_EST = 4
_ESTIMATED_OUTPUT_TOKENS = 2000  # writer output budget per deepening


def _estimate_call_cost_usd(
    *,
    system_prompt: str,
    user_msg: str,
    output_tokens: int = _ESTIMATED_OUTPUT_TOKENS,
) -> float:
    """Coarse pre-flight cost estimate for one writer call.

    Auto-decided heuristic per W9/D4 spec: prompt chars / 4 →
    tokens × prompt rate + fixed output budget × output rate. Drift
    from actuals is acceptable — the ``llm_calls`` row carries the
    truth post-flight. This only fires the pre-flight refusal when
    the upper bound would clearly exceed the cap.
    """
    prompt_tokens = max(0, (len(system_prompt) + len(user_msg)) // _CHARS_PER_TOKEN_EST)
    return (
        prompt_tokens * _ESTIMATED_PROMPT_USD_PER_TOKEN
        + output_tokens * _ESTIMATED_OUTPUT_USD_PER_TOKEN
    )


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
# Audit events — W9/D4
# ---------------------------------------------------------------------------
# The audit_events table (not audit_log — spec drift, naming-only)
# already has the ``action`` column granularity we need; no schema
# change. ``actor_user_id`` is the triggering consultant for
# ``triggered`` / ``accepted`` / ``rejected``, and NULL for
# system-driven ``completed`` / ``failed`` / ``cost_cap_exceeded``.


async def _audit_deepening(
    action: str,
    *,
    actor_user_id: UUID | None,
    deepening_id: UUID,
    payload: dict[str, Any],
) -> None:
    """Append one ``audit_events`` row for a deepening lifecycle event.

    Best-effort — never raises; audit-log hiccups must not abort
    the pipeline.
    """
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_events
                  (actor_user_id, action, resource_type, resource_id, payload)
                VALUES
                  ($1::uuid, $2, 'section_deepening', $3, $4::jsonb)
                """,
                actor_user_id,
                action,
                str(deepening_id),
                json.dumps(payload),
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("audit insert skipped for %s/%s: %s", action, deepening_id, e)


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


def _build_mode_aware_user_msg(
    *,
    section_path: str,
    original_section: Any,
    depth_directive: str | None,
    new_chunks: list[dict[str, Any]],
    resolved_mode: ResolvedConsultingMode | None,
    schema_class_name: str,
) -> str:
    """Compose the user message for the focused deepening writer pass.

    Mode-aware additions (W9/D4): leads with display_name + slug so
    the LLM sees what kind of memo this is; stitches in the resolved
    mode's ``writer_overlay`` (firm-overridden when applicable); names
    the schema class + section path explicitly so the LLM understands
    which Pydantic validators will run against the output.
    """
    directive_block = (
        depth_directive.strip()
        if depth_directive
        else "(no specific directive — produce a generally deeper, better-grounded version)"
    )
    mode_header = ""
    overlay_block = ""
    if resolved_mode is not None:
        mode_header = (
            f"Engagement mode: {resolved_mode.display_name} (slug: {resolved_mode.name})\n"
        )
        if (resolved_mode.writer_overlay or "").strip():
            overlay_block = (
                f"\nMODE WRITER OVERLAY (firm-resolved, applies to the rewrite):\n"
                f"{resolved_mode.writer_overlay.strip()[:2500]}\n"
            )
    schema_block = (
        f"\nSchema class: {schema_class_name}\n"
        f"Section path: {section_path}\n"
        f"The Pydantic validator for this section path runs on the deepened output. "
        f"Field-level constraints (required keys, list min/max, literal enums, "
        f"non-empty citation lists, etc.) are enforced — schema violation fails "
        f"the deepening with no retry.\n"
    )
    return (
        f"{mode_header}{schema_block}{overlay_block}\n"
        f"Depth directive:\n{directive_block}\n\n"
        f"Original section (JSON):\n{json.dumps(original_section, ensure_ascii=False, indent=2)[:6000]}\n\n"
        f"Newly retrieved evidence chunks (cite their ids as claim_ids):\n"
        f"{_format_chunks_for_prompt(new_chunks)}\n\n"
        f"Produce the deepened section JSON now. Same shape as the original; "
        f"no extra fields; no markdown wrapper."
    )


async def _call_deepening_writer(
    *,
    section_path: str,
    original_section: Any,
    depth_directive: str | None,
    new_chunks: list[dict[str, Any]],
    session_id: UUID,
    resolved_mode: ResolvedConsultingMode | None,
    schema_class_name: str,
) -> tuple[Any, list[str], str]:
    """Run the focused writer pass; return
    ``(deepened_section, new_claim_ids_used, user_msg)``.

    ``user_msg`` is returned for cost-estimation pre-flight + test
    introspection (so tests can assert the writer_overlay landed in
    the prompt without having to spy on ``llm_call_for_task``).
    """
    user_msg = _build_mode_aware_user_msg(
        section_path=section_path,
        original_section=original_section,
        depth_directive=depth_directive,
        new_chunks=new_chunks,
        resolved_mode=resolved_mode,
        schema_class_name=schema_class_name,
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
    return parsed, new_ids, user_msg


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
    await _audit_deepening(
        "section_deepening.triggered",
        actor_user_id=triggered_by,
        deepening_id=deepening_id,
        payload={
            "session_id": str(request.session_id),
            "section_path": request.section_path,
            "depth_directive": request.depth_directive,
        },
    )
    await _mark_running(deepening_id)

    # W9/D4: resolve mode + writer schema for the engagement. Mode
    # resolution failure is non-blocking — we fall through to a
    # mode-less rewrite (matches D1 behaviour). Schema lookup falls
    # back to GeneralReportPayload when the mode isn't in the
    # registry.
    resolved_mode: ResolvedConsultingMode | None = None
    schema_cls: type = GeneralReportPayload
    try:
        async with acquire() as conn:
            sess_row = await conn.fetchrow(
                "SELECT report_mode FROM sessions WHERE id=$1::uuid",
                request.session_id,
            )
        mode_name = str((sess_row or {}).get("report_mode") or "general")
        try:
            resolved_mode = await resolve_mode(
                mode_name, firm_id=firm_id, engagement_id=request.session_id
            )
        except Exception:  # noqa: BLE001
            logger.exception("mode resolution failed for deepening %s; continuing mode-less", deepening_id)
        schema_cls = get_writer_schema(mode_name)
    except Exception:  # noqa: BLE001
        logger.exception("schema lookup failed for deepening %s", deepening_id)

    try:
        already_cited = _existing_claim_ids(original_section)
        query = _build_retrieval_query(original_section, request.depth_directive)
        new_chunks = await _retrieve_new_chunks(
            request.session_id, query, already_cited
        )

        # W9/D4: cost-cap pre-flight. Build the user_msg to estimate
        # the prompt-size cost; refuse if over the per-run cap. Don't
        # fire any LLM call in this branch.
        preview_msg = _build_mode_aware_user_msg(
            section_path=request.section_path,
            original_section=original_section,
            depth_directive=request.depth_directive,
            new_chunks=new_chunks,
            resolved_mode=resolved_mode,
            schema_class_name=schema_cls.__name__,
        )
        est_cost = _estimate_call_cost_usd(
            system_prompt=SECTION_DEEPENING_WRITER_PROMPT,
            user_msg=preview_msg,
        )
        if est_cost > MAX_DEEPENING_COST_USD:
            wall = time.perf_counter() - t0
            reason = (
                f"exceeded_per_run_cost_cap: estimated ${est_cost:.4f} > "
                f"${MAX_DEEPENING_COST_USD:.2f} cap "
                f"(prompt chars: {len(SECTION_DEEPENING_WRITER_PROMPT) + len(preview_msg)})"
            )
            await _persist_failed(deepening_id, reason=reason, wall_seconds=wall)
            await _audit_deepening(
                "section_deepening.cost_cap_exceeded",
                actor_user_id=None,
                deepening_id=deepening_id,
                payload={
                    "session_id": str(request.session_id),
                    "section_path": request.section_path,
                    "estimated_cost_usd": round(est_cost, 4),
                    "cap_usd": MAX_DEEPENING_COST_USD,
                },
            )
            return DeepeningResult(
                deepening_id=deepening_id,
                section_path=request.section_path,
                original_section_json=original_section,
                deepened_section_json=None,
                status="failed",
                failure_reason=reason,
                wall_seconds=wall,
            )

        deepened_section, new_claim_ids, _user_msg = await _call_deepening_writer(
            section_path=request.section_path,
            original_section=original_section,
            depth_directive=request.depth_directive,
            new_chunks=new_chunks,
            session_id=request.session_id,
            resolved_mode=resolved_mode,
            schema_class_name=schema_cls.__name__,
        )

        # W9/D4: post-LLM schema validation. The deepened section
        # must validate against the type at section_path on the
        # resolved schema (M&A synergies still need basis_citations,
        # 2x2 still needs ≥2 items, etc.). No retries — hard rule.
        try:
            errors = validate_section_against_schema(
                schema_cls, request.section_path, deepened_section
            )
        except SchemaPathError as e:
            # The section_path resolved against the runtime payload
            # at request time but doesn't resolve against the
            # schema class — implies a mode-vs-payload mismatch
            # (e.g. M&A path on a general engagement). Treat as
            # failure with the path error verbatim.
            errors = [f"schema-path: {e}"]

        if errors:
            wall = time.perf_counter() - t0
            reason = (
                f"Deepened {request.section_path} failed schema validation: "
                + "; ".join(errors[:5])
            )
            await _persist_failed(deepening_id, reason=reason, wall_seconds=wall)
            await _audit_deepening(
                "section_deepening.failed",
                actor_user_id=None,
                deepening_id=deepening_id,
                payload={
                    "session_id": str(request.session_id),
                    "section_path": request.section_path,
                    "failure_reason": reason[:500],
                    "validation_errors": errors[:10],
                },
            )
            return DeepeningResult(
                deepening_id=deepening_id,
                section_path=request.section_path,
                original_section_json=original_section,
                deepened_section_json=deepened_section,  # preserve for forensic inspection
                status="failed",
                failure_reason=reason,
                wall_seconds=wall,
            )

        # New claim ids = those in the deepened section but not in
        # the original section's cited set. Bounded sweep, no LLM.
        truly_new = sorted(set(new_claim_ids) - already_cited)

        wall = time.perf_counter() - t0
        # Cost is captured by the cost-tracking row in ``llm_calls`` for
        # the writer task call; pulling it back requires an extra
        # query. We leave cost_usd=0.0 on the deepening row — the
        # truth lives in llm_calls.
        await _persist_complete(
            deepening_id,
            deepened_section=deepened_section,
            new_claim_ids=truly_new,
            new_evidence_chunks_used=len(new_chunks),
            cost_usd=0.0,
            wall_seconds=wall,
        )
        await _audit_deepening(
            "section_deepening.completed",
            actor_user_id=None,
            deepening_id=deepening_id,
            payload={
                "session_id": str(request.session_id),
                "section_path": request.section_path,
                "wall_seconds": round(wall, 2),
                "new_chunks": len(new_chunks),
                "new_claim_ids": truly_new,
            },
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
        await _audit_deepening(
            "section_deepening.failed",
            actor_user_id=None,
            deepening_id=deepening_id,
            payload={
                "session_id": str(request.session_id),
                "section_path": request.section_path,
                "failure_reason": reason[:500],
            },
        )
        return DeepeningResult(
            deepening_id=deepening_id,
            section_path=request.section_path,
            original_section_json=original_section,
            deepened_section_json=None,
            status="failed",
            failure_reason=reason,
            wall_seconds=wall,
        )
