"""DB queries for artifacts (memo / deck / model / chart)."""

from __future__ import annotations

import json
from typing import Any

from db.connection import acquire


def _row(r: Any) -> dict[str, Any]:
    doc = r["document_json"]
    if isinstance(doc, str):
        try:
            doc = json.loads(doc)
        except Exception:
            doc = {}
    return {
        "id": str(r["id"]),
        "engagement_id": str(r["engagement_id"]),
        "type": r["type"],
        "title": r["title"],
        "status": r["status"],
        "document_json": doc,
        "source_report_id": str(r["source_report_id"]) if r["source_report_id"] else None,
        "created_by": str(r["created_by"]) if r["created_by"] else None,
        "updated_by": str(r["updated_by"]) if r["updated_by"] else None,
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    }


async def insert_artifact(
    *,
    engagement_id: str,
    type_: str,
    title: str,
    document_json: dict[str, Any],
    source_report_id: str | None = None,
    created_by: str | None = None,
    status: str = "draft",
) -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO artifacts (engagement_id, type, title, status, document_json,
                                   source_report_id, created_by, updated_by)
            VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::uuid, $7::uuid, $7::uuid)
            RETURNING id, engagement_id, type, title, status, document_json,
                      source_report_id, created_by, updated_by, created_at, updated_at
            """,
            engagement_id,
            type_,
            title.strip()[:512] or "Untitled",
            status,
            json.dumps(document_json),
            source_report_id,
            created_by,
        )
    return _row(row)


async def get_artifact(artifact_id: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, engagement_id, type, title, status, document_json,
                   source_report_id, created_by, updated_by, created_at, updated_at
            FROM artifacts WHERE id = $1::uuid
            """,
            artifact_id,
        )
    return _row(row) if row else None


async def list_artifacts_for_engagement(engagement_id: str) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, engagement_id, type, title, status, document_json,
                   source_report_id, created_by, updated_by, created_at, updated_at
            FROM artifacts WHERE engagement_id = $1::uuid
            ORDER BY updated_at DESC
            """,
            engagement_id,
        )
    return [_row(r) for r in rows]


async def update_artifact(
    artifact_id: str,
    *,
    title: str | None = None,
    status: str | None = None,
    document_json: dict[str, Any] | None = None,
    updated_by: str | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = []
    params: list[Any] = []
    idx = 1

    def add(col: str, val: Any) -> None:
        nonlocal idx
        sets.append(f"{col} = ${idx}")
        params.append(val)
        idx += 1

    if title is not None:
        add("title", title.strip()[:512] or "Untitled")
    if status is not None:
        if status not in ("draft", "review", "final"):
            raise ValueError(f"invalid status: {status}")
        add("status", status)
    if document_json is not None:
        sets.append(f"document_json = ${idx}::jsonb")
        params.append(json.dumps(document_json))
        idx += 1
    if updated_by is not None:
        sets.append(f"updated_by = ${idx}::uuid")
        params.append(updated_by)
        idx += 1
    sets.append("updated_at = NOW()")

    sql = f"UPDATE artifacts SET {', '.join(sets)} WHERE id = ${idx}::uuid"
    params.append(artifact_id)
    async with acquire() as conn:
        await conn.execute(sql, *params)
    return await get_artifact(artifact_id)


async def delete_artifact(artifact_id: str) -> bool:
    async with acquire() as conn:
        result = await conn.execute("DELETE FROM artifacts WHERE id = $1::uuid", artifact_id)
    return result.split()[-1] != "0"
