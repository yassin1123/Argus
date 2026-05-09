import json
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from db.connection import acquire
from models.evidence import EvidenceObject
from models.report import ReportRow, WriterReportPayload


def _vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in vec) + "]"


async def create_session(
    session_id: str,
    title: str,
    query: str,
    status: str = "draft",
    *,
    report_mode: str = "general",
    created_by_user_id: str | None = None,
) -> None:
    async with acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO sessions (id, title, query, status, report_mode, created_by_user_id, updated_at)
                VALUES ($1::uuid, $2, $3, $4, $5, $6::uuid, NOW())
                """,
                session_id,
                title,
                query,
                status,
                report_mode,
                created_by_user_id,
            )
            # Creator gets a `lead` membership automatically.
            if created_by_user_id:
                await conn.execute(
                    """
                    INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
                    VALUES ($1::uuid, $2::uuid, 'lead', $2::uuid)
                    ON CONFLICT (engagement_id, user_id) DO NOTHING
                    """,
                    session_id,
                    created_by_user_id,
                )


async def save_session_intake_questions(session_id: str, questions: list[Any]) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions SET intake_questions = $2::jsonb, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            session_id,
            json.dumps(questions),
        )


async def save_session_intake_answers(session_id: str, answers: list[Any]) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions SET intake_answers = $2::jsonb, updated_at = NOW()
            WHERE id = $1::uuid
            """,
            session_id,
            json.dumps(answers),
        )


async def append_conversation_turn(
    session_id: str,
    role: str,
    content: str,
    *,
    intent: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(MAX(turn_index), -1) + 1 AS next_idx
            FROM conversation_turns WHERE session_id = $1::uuid
            """,
            session_id,
        )
        ti = int(row["next_idx"]) if row else 0
        r = await conn.fetchrow(
            """
            INSERT INTO conversation_turns (session_id, role, content, turn_index, intent, metadata)
            VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb)
            RETURNING id, turn_index, created_at
            """,
            session_id,
            role,
            content,
            ti,
            intent,
            json.dumps(metadata or {}),
        )
    return {
        "id": str(r["id"]),
        "turn_index": int(r["turn_index"]),
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


async def list_conversation_turns(session_id: str) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, role, content, turn_index, intent, metadata, created_at
            FROM conversation_turns
            WHERE session_id = $1::uuid
            ORDER BY turn_index ASC, created_at ASC
            """,
            session_id,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        meta = r["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        out.append(
            {
                "id": str(r["id"]),
                "role": r["role"],
                "content": r["content"],
                "turn_index": int(r["turn_index"]),
                "intent": r["intent"],
                "metadata": meta if isinstance(meta, dict) else {},
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
        )
    return out


async def clear_pipeline_artifacts(session_id: str) -> None:
    async with acquire() as conn:
        await conn.execute("DELETE FROM export_artifact_cache WHERE session_id = $1::uuid", session_id)
        await conn.execute("DELETE FROM pipeline_events WHERE session_id = $1::uuid", session_id)
        await conn.execute("DELETE FROM claim_support_rows WHERE session_id = $1::uuid", session_id)
        await conn.execute("DELETE FROM evaluations WHERE session_id = $1::uuid", session_id)
        await conn.execute("DELETE FROM deck_blueprints WHERE session_id = $1::uuid", session_id)
        await conn.execute("DELETE FROM reports WHERE session_id = $1::uuid", session_id)
        await conn.execute("DELETE FROM evidence_objects WHERE session_id = $1::uuid", session_id)
        await conn.execute("DELETE FROM agent_outputs WHERE session_id = $1::uuid", session_id)
        await conn.execute(
            """
            UPDATE sessions SET
                gap_report = '{}'::jsonb,
                metadata = COALESCE(metadata, '{}'::jsonb) - 'retrieval_hits',
                pipeline_state = 'idle',
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            session_id,
        )


async def update_pipeline_state(session_id: str, state: str) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions SET pipeline_state = $2, updated_at = NOW() WHERE id = $1::uuid
            """,
            session_id,
            state,
        )
    await insert_pipeline_event(
        session_id,
        event_type="pipeline_state",
        stage=state,
        status="set",
        payload={},
    )


async def insert_pipeline_event(
    session_id: str,
    *,
    event_type: str,
    stage: str = "",
    status: str = "",
    duration_ms: int | None = None,
    model_used: str | None = None,
    retry_count: int = 0,
    token_in: int | None = None,
    token_out: int | None = None,
    payload: dict[str, Any] | None = None,
) -> int | None:
    """Persist a pipeline event for SSE / audit. Returns serial id or None on failure."""
    pl = payload if payload is not None else {}
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO pipeline_events (
                    session_id, event_type, stage, status, duration_ms, model_used,
                    retry_count, token_in, token_out, payload
                )
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
                RETURNING id
                """,
                session_id,
                event_type,
                stage,
                status,
                duration_ms,
                model_used,
                retry_count,
                token_in,
                token_out,
                json.dumps(pl),
            )
        return int(row["id"]) if row else None
    except Exception:
        return None


async def list_pipeline_events_after(
    session_id: str,
    after_id: int = 0,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, event_type, stage, status, created_at, duration_ms,
                   model_used, retry_count, token_in, token_out, payload
            FROM pipeline_events
            WHERE session_id = $1::uuid AND id > $2
            ORDER BY id ASC
            LIMIT $3
            """,
            session_id,
            after_id,
            limit,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": int(r["id"]),
                "session_id": str(r["session_id"]),
                "event_type": r["event_type"],
                "stage": r["stage"],
                "status": r["status"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "duration_ms": r["duration_ms"],
                "model_used": r["model_used"],
                "retry_count": r["retry_count"],
                "token_in": r["token_in"],
                "token_out": r["token_out"],
                "payload": r["payload"] if isinstance(r["payload"], dict) else {},
            }
        )
    return out


async def merge_session_metadata(session_id: str, patch: dict[str, Any]) -> None:
    """Shallow-merge `patch` into sessions.metadata (JSONB)."""
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions SET
                metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb,
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            session_id,
            json.dumps(patch),
        )


async def append_pipeline_trace_events(session_id: str, events: list[dict[str, Any]]) -> None:
    """Append trace entries to metadata.pipeline_trace (JSON array)."""
    if not events:
        return
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions SET
                metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{pipeline_trace}',
                    COALESCE(metadata->'pipeline_trace', '[]'::jsonb) || $2::jsonb
                ),
                updated_at = NOW()
            WHERE id = $1::uuid
            """,
            session_id,
            json.dumps(events),
        )


async def update_session_status(session_id: str, status: str) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions SET status = $2, updated_at = NOW() WHERE id = $1::uuid
            """,
            session_id,
            status,
        )


async def update_session_query(session_id: str, query: str, title: str | None = None) -> None:
    async with acquire() as conn:
        if title is not None:
            await conn.execute(
                """
                UPDATE sessions SET query = $2, title = $3, updated_at = NOW() WHERE id = $1::uuid
                """,
                session_id,
                query,
                title,
            )
        else:
            await conn.execute(
                """
                UPDATE sessions SET query = $2, updated_at = NOW() WHERE id = $1::uuid
                """,
                session_id,
                query,
            )


async def list_sessions(*, user_id: str | None = None) -> list[dict[str, Any]]:
    """List engagements.

    When user_id is provided, scope to engagements where the user is a member
    OR where the engagement is a public demo seed (metadata.demo=true).
    """
    async with acquire() as conn:
        if user_id:
            rows = await conn.fetch(
                """
                SELECT DISTINCT s.id, s.title, s.query, s.status, s.created_at, s.updated_at,
                       s.metadata, s.gap_report, s.pipeline_state, s.report_mode,
                       (SELECT COUNT(*)::int FROM evidence_objects eo WHERE eo.session_id = s.id) AS evidence_count,
                       (SELECT LEFT(TRIM(r.recommendation), 220) FROM reports r WHERE r.session_id = s.id LIMIT 1)
                         AS recommendation_preview,
                       em.role AS my_role
                FROM sessions s
                LEFT JOIN engagement_memberships em
                  ON em.engagement_id = s.id AND em.user_id = $1::uuid
                WHERE em.user_id = $1::uuid
                   OR (s.metadata ->> 'demo')::boolean IS TRUE
                ORDER BY s.created_at DESC
                """,
                user_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT s.id, s.title, s.query, s.status, s.created_at, s.updated_at, s.metadata, s.gap_report,
                       s.pipeline_state, s.report_mode,
                       (SELECT COUNT(*)::int FROM evidence_objects eo WHERE eo.session_id = s.id) AS evidence_count,
                       (SELECT LEFT(TRIM(r.recommendation), 220) FROM reports r WHERE r.session_id = s.id LIMIT 1)
                         AS recommendation_preview
                FROM sessions s
                ORDER BY s.created_at DESC
                """
            )
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _session_dict(r)
        # Surface the user's role on each engagement (None for public demo seeds).
        if "my_role" in r.keys():
            d["my_role"] = r["my_role"]
        out.append(d)
    return out


async def delete_session(session_id: str) -> bool:
    async with acquire() as conn:
        result = await conn.execute("DELETE FROM sessions WHERE id = $1::uuid", session_id)
    return result.split()[-1] != "0"


async def get_session_row(session_id: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, title, query, status, created_at, updated_at, metadata, gap_report,
                   pipeline_state, report_mode, intake_questions, intake_answers,
                   created_by_user_id
            FROM sessions WHERE id = $1::uuid
            """,
            session_id,
        )
    if not row:
        return None
    return _session_dict(row)


async def get_session_detail(session_id: str) -> dict[str, Any] | None:
    base = await get_session_row(session_id)
    if not base:
        return None
    async with acquire() as conn:
        outputs = await conn.fetch(
            """
            SELECT id, agent_name, input, output, duration_ms, token_count, created_at
            FROM agent_outputs WHERE session_id = $1::uuid ORDER BY created_at ASC
            """,
            session_id,
        )
        files = await conn.fetch(
            """
            SELECT id, filename, file_type FROM uploaded_files
            WHERE session_id = $1::uuid ORDER BY created_at ASC
            """,
            session_id,
        )
        report_row = await conn.fetchrow(
            """
            SELECT id, session_id, recommendation, confidence_level, summary,
                   key_reasons, risks, counterarguments, next_steps, sources,
                   raw_output, caveats, evidence_bundle, verification,
                   evidence_count, unsupported_claim_count, consulting_payload,
                   reasoning_graph, claim_support, structured_answer, created_at
            FROM reports WHERE session_id = $1::uuid
            """,
            session_id,
        )
        ev_rows = await conn.fetch(
            """
            SELECT id, session_id, task_id, claim, quote, source_title, source_url,
                   source_date, source_type, source_score, confidence, is_inference, created_at
            FROM evidence_objects WHERE session_id = $1::uuid ORDER BY created_at ASC
            """,
            session_id,
        )
    base["agent_outputs"] = [_agent_output_dict(r) for r in outputs]
    base["uploaded_files"] = [
        {"id": str(r["id"]), "filename": r["filename"], "file_type": r["file_type"]} for r in files
    ]
    base["report"] = _report_dict(report_row) if report_row else None
    base["evidence_objects"] = [EvidenceObject.from_db_row(r).model_dump(mode="json") for r in ev_rows]
    return base


async def save_agent_output(
    session_id: str,
    agent_name: str,
    input_text: str | None,
    output_text: str,
    duration_ms: int | None = None,
    token_count: int | None = None,
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agent_outputs (session_id, agent_name, input, output, duration_ms, token_count)
            VALUES ($1::uuid, $2, $3, $4, $5, $6)
            """,
            session_id,
            agent_name,
            input_text,
            output_text,
            duration_ms,
            token_count,
        )


async def save_report(
    session_id: str,
    payload: WriterReportPayload,
    raw_output: str | None,
    evidence_bundle: list[Any] | None = None,
    *,
    verification: dict[str, Any] | None = None,
    evidence_count: int = 0,
    unsupported_claim_count: int = 0,
    consulting_payload: dict[str, Any] | None = None,
    reasoning_graph: dict[str, Any] | None = None,
    claim_support: list[dict[str, Any]] | None = None,
) -> str | None:
    """Persist report; returns report id (UUID string) when created/updated."""
    sources_json = [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in payload.sources]  # type: ignore[arg-type]
    bundle = evidence_bundle if evidence_bundle is not None else []
    ver = verification if verification is not None else {}
    consult = consulting_payload if consulting_payload is not None else {}
    rg = reasoning_graph if reasoning_graph is not None else {}
    cs = claim_support if claim_support is not None else []
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO reports (
                session_id, recommendation, confidence_level, summary,
                key_reasons, risks, counterarguments, next_steps, sources, raw_output, caveats,
                evidence_bundle, verification, evidence_count, unsupported_claim_count,
                consulting_payload, reasoning_graph, claim_support
            ) VALUES (
                $1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb, $10, $11,
                $12::jsonb, $13::jsonb, $14, $15, $16::jsonb, $17::jsonb, $18::jsonb
            )
            ON CONFLICT (session_id) DO UPDATE SET
                recommendation = EXCLUDED.recommendation,
                confidence_level = EXCLUDED.confidence_level,
                summary = EXCLUDED.summary,
                key_reasons = EXCLUDED.key_reasons,
                risks = EXCLUDED.risks,
                counterarguments = EXCLUDED.counterarguments,
                next_steps = EXCLUDED.next_steps,
                sources = EXCLUDED.sources,
                raw_output = EXCLUDED.raw_output,
                caveats = EXCLUDED.caveats,
                evidence_bundle = EXCLUDED.evidence_bundle,
                verification = EXCLUDED.verification,
                evidence_count = EXCLUDED.evidence_count,
                unsupported_claim_count = EXCLUDED.unsupported_claim_count,
                consulting_payload = EXCLUDED.consulting_payload,
                reasoning_graph = EXCLUDED.reasoning_graph,
                claim_support = EXCLUDED.claim_support,
                created_at = NOW()
            RETURNING id
            """,
            session_id,
            payload.recommendation,
            payload.confidence_level,
            payload.summary,
            json.dumps(payload.key_reasons),
            json.dumps(payload.risks),
            json.dumps(payload.counterarguments),
            json.dumps(payload.next_steps),
            json.dumps(sources_json),
            raw_output,
            payload.caveats or "",
            json.dumps(bundle),
            json.dumps(ver),
            evidence_count,
            unsupported_claim_count,
            json.dumps(consult),
            json.dumps(rg),
            json.dumps(cs),
        )
    return str(row["id"]) if row else None


# reports table has UNIQUE(session_id) via unique index - need ON CONFLICT (session_id)
# PostgreSQL: ON CONFLICT requires a unique constraint - we have idx_reports_session_id UNIQUE

async def get_report(session_id: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, recommendation, confidence_level, summary,
                   key_reasons, risks, counterarguments, next_steps, sources,
                   raw_output, caveats, evidence_bundle, verification,
                   evidence_count, unsupported_claim_count, consulting_payload,
                   reasoning_graph, claim_support, structured_answer, created_at
            FROM reports WHERE session_id = $1::uuid
            """,
            session_id,
        )
    if not row:
        return None
    out = _report_dict(row)
    sa = row["structured_answer"]
    if isinstance(sa, str):
        try:
            out["structured_answer"] = json.loads(sa)
        except Exception:
            out["structured_answer"] = None
    else:
        out["structured_answer"] = sa
    return out


async def save_structured_answer(report_id: str, structured_answer: dict[str, Any]) -> None:
    """Persist (or replace) the structured answer for a report."""
    async with acquire() as conn:
        await conn.execute(
            "UPDATE reports SET structured_answer = $2::jsonb WHERE id = $1::uuid",
            report_id,
            json.dumps(structured_answer),
        )


async def save_uploaded_file(
    file_id: str,
    session_id: str,
    filename: str,
    file_type: str,
    content: str,
    original_size: int | None,
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO uploaded_files (id, session_id, filename, file_type, content, original_size)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
            """,
            file_id,
            session_id,
            filename,
            file_type,
            content,
            original_size,
        )


async def save_embeddings(
    session_id: str,
    file_id: str | None,
    chunks: list[str],
    embeddings: list[list[float]],
    chunk_metas: list[dict[str, Any]] | None = None,
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings length mismatch")
    metas = chunk_metas if chunk_metas is not None else [{} for _ in chunks]
    if len(metas) != len(chunks):
        raise ValueError("chunk_metas length mismatch")
    async with acquire() as conn:
        for idx, (chunk, emb, meta) in enumerate(zip(chunks, embeddings, metas)):
            eid = str(uuid.uuid4())
            vec = _vector_literal(emb)
            await conn.execute(
                """
                INSERT INTO embeddings (id, session_id, file_id, chunk_text, chunk_index, embedding, chunk_meta)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::vector, $7::jsonb)
                """,
                eid,
                session_id,
                file_id,
                chunk,
                idx,
                vec,
                json.dumps(meta or {}),
            )


async def semantic_search(session_id: str, query_embedding: list[float], top_k: int = 5) -> list[str]:
    hits = await semantic_search_hits(session_id, query_embedding, top_k=top_k)
    return [h["chunk_text"] for h in hits]


async def semantic_search_hits(
    session_id: str,
    query_embedding: list[float],
    *,
    top_k: int = 5,
    candidate_pool: int | None = None,
    min_similarity: float = 0.0,
) -> list[dict[str, Any]]:
    """Return chunks with cosine similarity (1 - distance) and file provenance."""
    pool = max(top_k, candidate_pool or top_k * 3)
    vec = _vector_literal(query_embedding)
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                e.id,
                e.chunk_text,
                e.chunk_index,
                e.file_id,
                e.chunk_meta,
                uf.filename,
                uf.file_type,
                (1 - (e.embedding <=> $2::vector))::float AS similarity
            FROM embeddings e
            LEFT JOIN uploaded_files uf ON uf.id = e.file_id
            WHERE e.session_id = $1::uuid
            ORDER BY e.embedding <=> $2::vector
            LIMIT $3
            """,
            session_id,
            vec,
            pool,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        sim = float(r["similarity"])
        if sim < min_similarity:
            continue
        out.append(
            {
                "id": r["id"],
                "chunk_text": r["chunk_text"],
                "chunk_index": r["chunk_index"],
                "file_id": r["file_id"],
                "chunk_meta": r["chunk_meta"],
                "filename": r["filename"] or "",
                "file_type": r["file_type"] or "",
                "similarity": sim,
            }
        )
    return out[:top_k]


async def get_uploaded_context_text(session_id: str, limit_chars: int = 12000) -> str:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT filename, file_type, content FROM uploaded_files
            WHERE session_id = $1::uuid ORDER BY created_at ASC
            """,
            session_id,
        )
    parts: list[str] = []
    total = 0
    for r in rows:
        header = f"--- File: {r['filename']} ({r['file_type']}) ---\n"
        chunk = header + (r["content"] or "")
        if total + len(chunk) > limit_chars:
            chunk = chunk[: max(0, limit_chars - total)]
        parts.append(chunk)
        total += len(chunk)
        if total >= limit_chars:
            break
    return "\n\n".join(parts)


def _preview_or_none(val: Any) -> str | None:
    if isinstance(val, str) and val.strip():
        return val.strip()
    return None


def _session_dict(row: Any) -> dict[str, Any]:
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    gap = row.get("gap_report")
    if gap is None:
        gap_obj: dict[str, Any] = {}
    elif isinstance(gap, str):
        gap_obj = json.loads(gap)
    elif isinstance(gap, dict):
        gap_obj = gap
    else:
        gap_obj = dict(gap)
    iq = row.get("intake_questions")
    ia = row.get("intake_answers")
    if isinstance(iq, str):
        iq = json.loads(iq)
    if isinstance(ia, str):
        ia = json.loads(ia)
    created_by = row.get("created_by_user_id") if "created_by_user_id" in row else None
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "query": row["query"],
        "status": row["status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "metadata": meta or {},
        "gap_report": gap_obj,
        "pipeline_state": str(row.get("pipeline_state") or "idle"),
        "report_mode": str(row.get("report_mode") or "general"),
        "evidence_count": int(row.get("evidence_count") or 0),
        "intake_questions": list(iq) if isinstance(iq, list) else [],
        "intake_answers": list(ia) if isinstance(ia, list) else [],
        "recommendation_preview": _preview_or_none(row.get("recommendation_preview")),
        "created_by_user_id": str(created_by) if created_by else None,
    }


def _agent_output_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "agent_name": row["agent_name"],
        "input": row["input"],
        "output": row["output"],
        "duration_ms": row["duration_ms"],
        "token_count": row["token_count"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def _report_dict(row: Any) -> dict[str, Any]:
    def _j(x: Any) -> Any:
        if isinstance(x, str):
            return json.loads(x)
        return x

    eb = row.get("evidence_bundle")
    if eb is None:
        evidence_bundle: list[Any] = []
    elif isinstance(eb, str):
        evidence_bundle = json.loads(eb)
    else:
        evidence_bundle = list(eb) if isinstance(eb, list) else _j(eb)

    ver = row.get("verification")
    if ver is None:
        verification: dict[str, Any] = {}
    elif isinstance(ver, str):
        verification = json.loads(ver)
    elif isinstance(ver, dict):
        verification = ver
    else:
        verification = dict(ver)

    cp = row.get("consulting_payload")
    if cp is None:
        consulting_payload: dict[str, Any] = {}
    elif isinstance(cp, str):
        consulting_payload = json.loads(cp)
    elif isinstance(cp, dict):
        consulting_payload = cp
    else:
        consulting_payload = dict(cp)

    rg = row.get("reasoning_graph")
    if rg is None:
        reasoning_graph: dict[str, Any] = {}
    elif isinstance(rg, str):
        reasoning_graph = json.loads(rg)
    elif isinstance(rg, dict):
        reasoning_graph = rg
    else:
        reasoning_graph = dict(rg)

    csup = row.get("claim_support")
    if csup is None:
        claim_support: list[Any] = []
    elif isinstance(csup, str):
        claim_support = json.loads(csup)
    elif isinstance(csup, list):
        claim_support = list(csup)
    else:
        parsed = _j(csup)
        claim_support = parsed if isinstance(parsed, list) else []

    sa = row.get("structured_answer") if "structured_answer" in row.keys() else None
    if isinstance(sa, str):
        try:
            sa = json.loads(sa)
        except Exception:
            sa = None

    return {
        "id": str(row["id"]),
        "session_id": str(row["session_id"]),
        "recommendation": row["recommendation"],
        "confidence_level": row["confidence_level"],
        "summary": row["summary"],
        "key_reasons": _j(row["key_reasons"]),
        "risks": _j(row["risks"]),
        "counterarguments": _j(row["counterarguments"]),
        "next_steps": _j(row["next_steps"]),
        "sources": _j(row["sources"]),
        "raw_output": row["raw_output"],
        "caveats": row["caveats"] or "",
        "evidence_bundle": evidence_bundle,
        "verification": verification,
        "evidence_count": int(row.get("evidence_count") or 0),
        "unsupported_claim_count": int(row.get("unsupported_claim_count") or 0),
        "consulting_payload": consulting_payload,
        "reasoning_graph": reasoning_graph,
        "claim_support": claim_support if isinstance(claim_support, list) else [],
        "structured_answer": sa,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def insert_evidence_objects(objs: list[EvidenceObject]) -> list[EvidenceObject]:
    """Insert rows; returns same objects with id, metadata, created_at set.

    ``metadata`` (Day 4) is serialised to jsonb so the citation popover
    can render source-type-specific breadcrumbs (e.g. firm-library
    title + category) without the schema needing to grow per source.
    """
    if not objs:
        return []
    out: list[EvidenceObject] = []
    async with acquire() as conn:
        for o in objs:
            md = json.dumps(o.metadata or {})
            row = await conn.fetchrow(
                """
                INSERT INTO evidence_objects (
                    session_id, task_id, claim, quote, source_title, source_url,
                    source_date, source_type, source_score, confidence, is_inference,
                    metadata
                )
                VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb)
                RETURNING id, session_id, task_id, claim, quote, source_title, source_url,
                          source_date, source_type, source_score, confidence, is_inference,
                          metadata, created_at
                """,
                o.session_id,
                o.task_id,
                o.claim,
                o.quote,
                o.source_title,
                o.source_url,
                o.source_date,
                o.source_type,
                o.source_score,
                o.confidence,
                o.is_inference,
                md,
            )
            out.append(EvidenceObject.from_db_row(row))
    return out


async def list_evidence_objects(session_id: str) -> list[EvidenceObject]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, task_id, claim, quote, source_title, source_url,
                   source_date, source_type, source_score, confidence, is_inference,
                   metadata, created_at
            FROM evidence_objects WHERE session_id = $1::uuid ORDER BY created_at ASC
            """,
            session_id,
        )
    return [EvidenceObject.from_db_row(r) for r in rows]


async def update_session_gap_report(session_id: str, gap_report: dict[str, Any]) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions SET gap_report = $2::jsonb, updated_at = NOW() WHERE id = $1::uuid
            """,
            session_id,
            json.dumps(gap_report),
        )


async def save_claim_evidence_links(
    report_id: str,
    links: list[tuple[str, str, str]],
) -> None:
    """links: (claim_ref, evidence_object_id, link_type)."""
    async with acquire() as conn:
        await conn.execute(
            "DELETE FROM claim_evidence_links WHERE report_id = $1::uuid",
            report_id,
        )
        if not links:
            return
        for claim_ref, eid, link_type in links:
            await conn.execute(
                """
                INSERT INTO claim_evidence_links (report_id, claim_ref, evidence_object_id, link_type)
                VALUES ($1::uuid, $2, $3::uuid, $4)
                """,
                report_id,
                claim_ref[:2000],
                eid,
                link_type[:64],
            )


async def save_deck_blueprint(session_id: str, blueprint: dict[str, Any]) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO deck_blueprints (session_id, blueprint)
            VALUES ($1::uuid, $2::jsonb)
            """,
            session_id,
            json.dumps(blueprint),
        )


async def get_export_artifact_cache(session_id: str, format_key: str, content_hash: str) -> bytes | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT bytes FROM export_artifact_cache
            WHERE session_id = $1::uuid AND format_key = $2 AND content_hash = $3
            """,
            session_id,
            format_key,
            content_hash,
        )
    if not row or row["bytes"] is None:
        return None
    b = row["bytes"]
    return bytes(b) if not isinstance(b, bytes) else b


async def save_export_artifact_cache(
    session_id: str, format_key: str, content_hash: str, data: bytes
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO export_artifact_cache (session_id, format_key, content_hash, bytes)
            VALUES ($1::uuid, $2, $3, $4)
            ON CONFLICT (session_id, format_key, content_hash) DO UPDATE SET
                bytes = EXCLUDED.bytes,
                created_at = NOW()
            """,
            session_id,
            format_key,
            content_hash,
            data,
        )


async def save_evaluation(session_id: str, metrics: dict[str, Any]) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO evaluations (session_id, metrics) VALUES ($1::uuid, $2::jsonb)
            """,
            session_id,
            json.dumps(metrics),
        )


async def list_evaluations_for_session(session_id: str) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, metrics, created_at FROM evaluations
            WHERE session_id = $1::uuid ORDER BY created_at ASC
            """,
            session_id,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        m = r["metrics"]
        if isinstance(m, str):
            m = json.loads(m)
        out.append(
            {
                "id": str(r["id"]),
                "metrics": m if isinstance(m, dict) else {},
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
        )
    return out


async def replace_claim_support_rows(
    session_id: str,
    report_id: str | None,
    rows: list[dict[str, Any]],
) -> None:
    async with acquire() as conn:
        await conn.execute("DELETE FROM claim_support_rows WHERE session_id = $1::uuid", session_id)
        if not rows:
            return
        rid = report_id if report_id else None
        for r in rows:
            eids = [str(x) for x in (r.get("evidence_object_ids") or []) if x]
            # Day 3 ensemble columns — present when core/nli/ensemble_enrich.py
            # has run, NULL otherwise so legacy rows / unit-test fixtures still
            # round-trip cleanly through this writer.
            nli_label = str(r["nli_label"])[:32] if r.get("nli_label") else None
            nli_conf = float(r["nli_confidence"]) if r.get("nli_confidence") is not None else None
            num_score = float(r["numeric_overlap_score"]) if r.get("numeric_overlap_score") is not None else None
            ent_score = float(r["entity_overlap_score"]) if r.get("entity_overlap_score") is not None else None
            num_missing = json.dumps(list(r.get("numeric_overlap_missing") or []))
            ent_missing = json.dumps(list(r.get("entity_overlap_missing") or []))
            ens_verdict = str(r["ensemble_verdict"])[:32] if r.get("ensemble_verdict") else None
            ens_reason = str(r["ensemble_reason"])[:1000] if r.get("ensemble_reason") else None
            await conn.execute(
                """
                INSERT INTO claim_support_rows (
                    session_id, report_id, claim_id, claim_text, evidence_object_ids,
                    support_type, verifier_verdict, contradiction_flag, staleness_hint,
                    entailment_score, weak_flag,
                    nli_label, nli_confidence,
                    numeric_overlap_score, numeric_overlap_missing,
                    entity_overlap_score, entity_overlap_missing,
                    ensemble_verdict, ensemble_reason
                ) VALUES (
                    $1::uuid, $2::uuid, $3, $4, $5::uuid[], $6, $7, $8, $9, $10, $11,
                    $12, $13, $14, $15::jsonb, $16, $17::jsonb, $18, $19
                )
                """,
                session_id,
                rid,
                str(r.get("claim_id", ""))[:256],
                str(r.get("claim_text", ""))[:8000],
                eids,
                str(r.get("support_type", "inference"))[:64],
                str(r["verifier_verdict"])[:64] if r.get("verifier_verdict") else None,
                bool(r.get("contradiction_flag")),
                str(r.get("staleness_hint") or "")[:2000],
                float(r.get("entailment_score") or 0.0),
                bool(r.get("weak_or_unsupported")),
                nli_label,
                nli_conf,
                num_score,
                num_missing,
                ent_score,
                ent_missing,
                ens_verdict,
                ens_reason,
            )
