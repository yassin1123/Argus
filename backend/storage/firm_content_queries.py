"""DB queries for the ``firm_content`` table.

Mirrors the shape of ``storage/source_queries.py`` for the legacy
``uploaded_files`` table — same conventions on async, lazy import,
explicit returns. Migration 025 created the table.
"""

from __future__ import annotations

import json
from typing import Any

from db.connection import acquire

CATEGORIES = (
    "playbook",
    "sector_primer",
    "prior_report",
    "framework",
    "methodology",
    "other",
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    out: dict[str, Any] = {}
    for k, v in dict(row).items():
        if hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        elif isinstance(v, list):
            out[k] = list(v)
        elif isinstance(v, dict):
            out[k] = dict(v)
        elif isinstance(v, (str, int, float, bool, type(None))):
            out[k] = v
        else:
            out[k] = str(v)
    return out


async def insert_firm_content(
    *,
    firm_id: str,
    title: str,
    category: str,
    description: str | None,
    intended_modes: list[str],
    sector_tags: list[str],
    source_filename: str | None,
    file_hash: str | None,
    trust_level: str,
    uploaded_by: str | None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}, got {category!r}")
    md = json.dumps(metadata or {})
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO firm_content (
                firm_id, title, category, description, intended_modes,
                sector_tags, source_filename, file_hash, trust_level,
                uploaded_by, metadata
            ) VALUES (
                $1::uuid, $2, $3, $4, $5::text[], $6::text[],
                $7, $8, $9, $10::uuid, $11::jsonb
            )
            RETURNING *
            """,
            firm_id,
            title,
            category,
            description,
            list(intended_modes or []),
            list(sector_tags or []),
            source_filename,
            file_hash,
            trust_level,
            uploaded_by,
            md,
        )
    return _row_to_dict(row)


async def find_active_by_filehash(
    firm_id: str, file_hash: str
) -> dict[str, Any] | None:
    """Idempotency lookup: returns the active (non-retired) firm_content
    row for this (firm_id, file_hash) tuple if one exists."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM firm_content
            WHERE firm_id = $1::uuid
              AND file_hash = $2
              AND retired_at IS NULL
            LIMIT 1
            """,
            firm_id,
            file_hash,
        )
    return _row_to_dict(row) if row else None


async def get_firm_content(firm_id: str, content_id: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM firm_content WHERE id = $1::uuid AND firm_id = $2::uuid",
            content_id,
            firm_id,
        )
    return _row_to_dict(row) if row else None


async def list_firm_content(
    firm_id: str,
    *,
    category: str | None = None,
    sector: str | None = None,
    mode: str | None = None,
    include_retired: bool = False,
) -> list[dict[str, Any]]:
    """List firm content with optional filters.

    All filters compose with AND. ``sector`` and ``mode`` use Postgres'
    array-membership operator (``= ANY``) so a single value matches when
    it appears anywhere in the row's array column.
    """
    where = ["firm_id = $1::uuid"]
    args: list[Any] = [firm_id]
    if not include_retired:
        where.append("retired_at IS NULL")
    if category:
        args.append(category)
        where.append(f"category = ${len(args)}")
    if sector:
        args.append(sector)
        where.append(f"${len(args)} = ANY(sector_tags)")
    if mode:
        args.append(mode)
        where.append(f"${len(args)} = ANY(intended_modes)")
    sql = (
        "SELECT * FROM firm_content WHERE "
        + " AND ".join(where)
        + " ORDER BY uploaded_at DESC"
    )
    async with acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [_row_to_dict(r) for r in rows]


async def update_firm_content(
    firm_id: str,
    content_id: str,
    *,
    title: str | None = None,
    description: str | None = None,
    intended_modes: list[str] | None = None,
    sector_tags: list[str] | None = None,
) -> dict[str, Any] | None:
    fields: list[str] = []
    args: list[Any] = []
    if title is not None:
        args.append(title)
        fields.append(f"title = ${len(args)}")
    if description is not None:
        args.append(description)
        fields.append(f"description = ${len(args)}")
    if intended_modes is not None:
        args.append(list(intended_modes))
        fields.append(f"intended_modes = ${len(args)}::text[]")
    if sector_tags is not None:
        args.append(list(sector_tags))
        fields.append(f"sector_tags = ${len(args)}::text[]")
    if not fields:
        return await get_firm_content(firm_id, content_id)
    args.append(content_id)
    args.append(firm_id)
    sql = (
        "UPDATE firm_content SET "
        + ", ".join(fields)
        + f" WHERE id = ${len(args) - 1}::uuid AND firm_id = ${len(args)}::uuid"
        + " RETURNING *"
    )
    async with acquire() as conn:
        row = await conn.fetchrow(sql, *args)
    return _row_to_dict(row) if row else None


async def retire_firm_content_row(
    firm_id: str, content_id: str, retired_by: str | None
) -> dict[str, Any] | None:
    """Mark the row retired and stamp retired_by. Caller stamps the chunks
    side via :func:`mark_chunks_retired`."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE firm_content
            SET retired_at = NOW(), retired_by = $3::uuid
            WHERE id = $1::uuid AND firm_id = $2::uuid AND retired_at IS NULL
            RETURNING *
            """,
            content_id,
            firm_id,
            retired_by,
        )
    return _row_to_dict(row) if row else None


async def update_chunk_count(content_id: str, delta_or_absolute: int, *, absolute: bool = True) -> None:
    """Set or increment ``firm_content.chunk_count``."""
    async with acquire() as conn:
        if absolute:
            await conn.execute(
                "UPDATE firm_content SET chunk_count = $2 WHERE id = $1::uuid",
                content_id,
                int(delta_or_absolute),
            )
        else:
            await conn.execute(
                "UPDATE firm_content SET chunk_count = chunk_count + $2 WHERE id = $1::uuid",
                content_id,
                int(delta_or_absolute),
            )


async def mark_chunks_retired(firm_id: str, content_id: str) -> int:
    """Stamp the retire timestamp into each chunk's metadata so retrieval
    can filter them. Returns the number of chunks touched.

    We do NOT delete the chunks — historical engagement citations to a
    retired playbook stay valid; only NEW retrieval excludes them.
    """
    async with acquire() as conn:
        result = await conn.fetchval(
            """
            WITH updated AS (
                UPDATE chunks
                SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{retired_at}',
                    to_jsonb(NOW()::text)
                )
                WHERE firm_id = $1::uuid
                  AND firm_content_id = $2::uuid
                  AND (metadata->>'retired_at') IS NULL
                RETURNING 1
            )
            SELECT count(*)::int FROM updated
            """,
            firm_id,
            content_id,
        )
    return int(result or 0)


async def list_chunks_for_content(
    firm_id: str, content_id: str, *, limit: int = 3
) -> list[dict[str, Any]]:
    """Return the first ``limit`` chunks belonging to one library item."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, content, position, page, section_heading, source_filename
            FROM chunks
            WHERE firm_id = $1::uuid AND firm_content_id = $2::uuid
            ORDER BY position ASC LIMIT $3
            """,
            firm_id,
            content_id,
            int(limit),
        )
    return [_row_to_dict(r) for r in rows]
