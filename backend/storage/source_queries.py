"""Source-management queries (list / get / update trust + scope)."""

from __future__ import annotations

from typing import Any

from db.connection import acquire


def _source_row(r: Any) -> dict[str, Any]:
    return {
        "id": str(r["id"]),
        "session_id": str(r["session_id"]) if r["session_id"] else None,
        "filename": r["filename"],
        "file_type": r["file_type"],
        "trust_level": r["trust_level"] or "web_general",
        "scope": r["scope"] or "engagement",
        "notes": r["notes"] or "",
        "source_url": r["source_url"],
        "original_size": int(r["original_size"]) if r["original_size"] is not None else None,
        "blob_id": str(r["blob_id"]) if r.get("blob_id") else None,
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "chunk_count": int(r["chunk_count"]) if r.get("chunk_count") is not None else 0,
    }


_LIST_SQL = """
SELECT
    f.id, f.session_id, f.filename, f.file_type, f.trust_level, f.scope,
    f.notes, f.source_url, f.original_size, f.blob_id, f.created_at,
    (SELECT COUNT(*)::int FROM chunks c WHERE c.source_file_id = f.id) AS chunk_count
FROM uploaded_files f
"""


async def list_sources_for_engagement(session_id: str) -> list[dict[str, Any]]:
    """Engagement-scoped sources for a single engagement (excludes firm-wide)."""
    async with acquire() as conn:
        rows = await conn.fetch(
            _LIST_SQL + " WHERE f.session_id = $1::uuid AND f.scope = 'engagement' ORDER BY f.created_at DESC",
            session_id,
        )
    return [_source_row(r) for r in rows]


async def list_firm_sources() -> list[dict[str, Any]]:
    """All firm-wide sources (visible across engagements)."""
    async with acquire() as conn:
        rows = await conn.fetch(
            _LIST_SQL + " WHERE f.scope = 'firm' ORDER BY f.created_at DESC",
        )
    return [_source_row(r) for r in rows]


async def list_visible_sources(session_id: str) -> list[dict[str, Any]]:
    """Everything visible inside an engagement: own sources + firm-wide."""
    async with acquire() as conn:
        rows = await conn.fetch(
            _LIST_SQL + " WHERE f.session_id = $1::uuid OR f.scope = 'firm' ORDER BY f.created_at DESC",
            session_id,
        )
    return [_source_row(r) for r in rows]


async def get_source(file_id: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            _LIST_SQL + " WHERE f.id = $1::uuid",
            file_id,
        )
    return _source_row(row) if row else None


async def update_source(
    file_id: str,
    *,
    title: str | None = None,
    trust_level: str | None = None,
    scope: str | None = None,
    notes: str | None = None,
) -> dict[str, Any] | None:
    """Patch user-controlled fields. Returns the updated source row, or None if not found."""
    sets: list[str] = []
    params: list[Any] = []
    idx = 1

    def add(col: str, val: Any) -> None:
        nonlocal idx
        sets.append(f"{col} = ${idx}")
        params.append(val)
        idx += 1

    if title is not None:
        add("filename", title.strip()[:1024])
    if trust_level is not None:
        if trust_level not in ("firm_vetted", "credible_external", "web_general", "contested"):
            raise ValueError(f"invalid trust_level: {trust_level}")
        add("trust_level", trust_level)
    if scope is not None:
        if scope not in ("engagement", "firm"):
            raise ValueError(f"invalid scope: {scope}")
        add("scope", scope)
    if notes is not None:
        add("notes", notes.strip()[:4000])

    if not sets:
        return await get_source(file_id)

    sql = f"UPDATE uploaded_files SET {', '.join(sets)} WHERE id = ${idx}::uuid"
    params.append(file_id)
    async with acquire() as conn:
        await conn.execute(sql, *params)
        # Propagate trust_level changes into chunks too.
        if trust_level is not None:
            await conn.execute(
                "UPDATE chunks SET trust_level = $1 WHERE source_file_id = $2::uuid",
                trust_level,
                file_id,
            )
    return await get_source(file_id)


async def delete_source(file_id: str) -> bool:
    async with acquire() as conn:
        result = await conn.execute("DELETE FROM uploaded_files WHERE id = $1::uuid", file_id)
    return result.split()[-1] != "0"
