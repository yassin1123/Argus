"""DB queries for source_blobs."""

from __future__ import annotations

from typing import Any

from db.connection import acquire


async def insert_source_blob(
    *,
    session_id: str,
    s3_key: str,
    size_bytes: int,
    content_type: str,
    sha256: str,
    uploaded_by: str | None,
) -> str:
    """Insert a row, return blob_id (UUID)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO source_blobs (session_id, s3_key, size_bytes, content_type, sha256, uploaded_by)
            VALUES ($1::uuid, $2, $3, $4, $5, $6::uuid)
            RETURNING id
            """,
            session_id,
            s3_key,
            int(size_bytes),
            content_type,
            sha256,
            uploaded_by,
        )
    return str(row["id"])


async def get_source_blob(blob_id: str) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, s3_key, size_bytes, content_type, sha256,
                   uploaded_by, uploaded_at
            FROM source_blobs WHERE id = $1::uuid
            """,
            blob_id,
        )
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "session_id": str(row["session_id"]) if row["session_id"] else None,
        "s3_key": row["s3_key"],
        "size_bytes": int(row["size_bytes"]),
        "content_type": row["content_type"],
        "sha256": row["sha256"],
        "uploaded_by": str(row["uploaded_by"]) if row["uploaded_by"] else None,
        "uploaded_at": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
    }


async def attach_blob_to_uploaded_file(uploaded_file_id: str, blob_id: str) -> None:
    """Link a row in `uploaded_files` to its raw blob in object storage."""
    async with acquire() as conn:
        await conn.execute(
            "UPDATE uploaded_files SET blob_id = $2::uuid WHERE id = $1::uuid",
            uploaded_file_id,
            blob_id,
        )


async def delete_source_blob_row(blob_id: str) -> None:
    async with acquire() as conn:
        await conn.execute("DELETE FROM source_blobs WHERE id = $1::uuid", blob_id)
