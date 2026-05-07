"""DB queries for the new `chunks` table."""

from __future__ import annotations

import json
from typing import Any, Sequence

from db.connection import acquire


def _vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


async def insert_chunks(
    *,
    session_id: str | None,
    blob_id: str | None,
    source_file_id: str | None,
    source_type: str,
    source_filename: str,
    source_url: str | None,
    trust_level: str,
    rows: list[dict[str, Any]],
) -> list[str]:
    """Insert a batch of chunks. `rows` items must include:
        content, content_hash, embedding (list[float]), position
    Optional per-row: page, slide, timestamp_str, speaker, section_heading,
        metadata (dict — serialised to jsonb).

    ``session_id`` may be ``None`` for firm-global / public sources
    (e.g. SEC EDGAR ingestion writes session-less chunks). Uploaded files
    still pass a real session_id, so the legacy path is unchanged.

    Returns a list of inserted chunk UUIDs.
    """
    if not rows:
        return []
    out: list[str] = []
    async with acquire() as conn:
        for r in rows:
            metadata = r.get("metadata") or {}
            metadata_json = json.dumps(metadata) if not isinstance(metadata, str) else metadata
            row = await conn.fetchrow(
                """
                INSERT INTO chunks (
                    session_id, blob_id, source_file_id, content, content_hash,
                    embedding, source_type, position, page, slide, timestamp_str,
                    speaker, section_heading, source_filename, source_url, trust_level,
                    metadata
                ) VALUES (
                    $1::uuid, $2::uuid, $3::uuid, $4, $5,
                    $6::vector, $7, $8, $9, $10, $11,
                    $12, $13, $14, $15, $16,
                    $17::jsonb
                )
                RETURNING id
                """,
                session_id,
                blob_id,
                source_file_id,
                r["content"],
                r["content_hash"],
                _vector_literal(r["embedding"]),
                source_type,
                int(r.get("position") or 0),
                r.get("page"),
                r.get("slide"),
                r.get("timestamp_str"),
                r.get("speaker"),
                r.get("section_heading"),
                source_filename[:1024] if source_filename else "",
                source_url,
                trust_level,
                metadata_json,
            )
            out.append(str(row["id"]))
    return out


async def list_chunks_for_source(source_file_id: str) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, content, source_type, position, page, slide,
                   timestamp_str, speaker, section_heading, source_filename,
                   source_url, trust_level, created_at
            FROM chunks
            WHERE source_file_id = $1::uuid
            ORDER BY position ASC
            """,
            source_file_id,
        )
    return [_chunk_dict(r) for r in rows]


async def list_chunks_for_session(session_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, content, source_type, position, page, slide,
                   timestamp_str, speaker, section_heading, source_filename,
                   source_url, trust_level, created_at
            FROM chunks
            WHERE session_id = $1::uuid
            ORDER BY created_at DESC, position ASC
            LIMIT $2
            """,
            session_id,
            limit,
        )
    return [_chunk_dict(r) for r in rows]


async def count_chunks_for_session(session_id: str) -> int:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*)::int AS n FROM chunks WHERE session_id = $1::uuid",
            session_id,
        )
    return int(row["n"]) if row else 0


def _chunk_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "session_id": str(row["session_id"]),
        "content": row["content"],
        "source_type": row["source_type"],
        "position": int(row["position"]),
        "page": row["page"],
        "slide": row["slide"],
        "timestamp_str": row["timestamp_str"],
        "speaker": row["speaker"],
        "section_heading": row["section_heading"],
        "source_filename": row["source_filename"] or "",
        "source_url": row["source_url"],
        "trust_level": row["trust_level"] or "web_general",
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
