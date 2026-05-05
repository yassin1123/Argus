"""Ingest pipeline — chunker → embedder → DB writer.

Runs synchronously inside the upload endpoint for MVP. v1 will move this to a
Celery worker so the upload endpoint returns 202 and the user gets progress
updates.
"""

from __future__ import annotations

import logging
from typing import Literal

from core.embeddings import embed_texts
from .chunking import Chunk, chunk_source

logger = logging.getLogger(__name__)

SourceKind = Literal["pdf", "transcript", "web", "csv", "json", "knowledge"]

# Default trust levels by source type. Phase 5 lets the user override per-source.
_TRUST_BY_KIND: dict[str, str] = {
    "pdf": "firm_vetted",
    "transcript": "firm_vetted",
    "csv": "firm_vetted",
    "json": "firm_vetted",
    "knowledge": "firm_vetted",
    "web": "web_general",
}


async def ingest(
    *,
    session_id: str,
    source_file_id: str | None,
    blob_id: str | None,
    source_kind: SourceKind,
    content: bytes | str,
    source_filename: str,
    source_url: str | None = None,
    trust_level: str | None = None,
) -> dict:
    """Chunk + embed + persist. Returns {chunks_inserted, chunk_ids}."""
    chunks: list[Chunk] = chunk_source(source_kind=source_kind, content=content)
    if not chunks:
        return {"chunks_inserted": 0, "chunk_ids": []}

    texts = [c.content for c in chunks]
    try:
        embeddings = await embed_texts(texts)
    except Exception as e:  # noqa: BLE001
        logger.exception("embedding failed")
        return {"chunks_inserted": 0, "chunk_ids": [], "error": str(e)}

    rows = []
    for c, vec in zip(chunks, embeddings):
        rows.append(
            {
                "content": c.content,
                "content_hash": c.content_hash,
                "embedding": vec,
                "position": c.position,
                "page": c.page,
                "slide": c.slide,
                "timestamp_str": c.timestamp_str,
                "speaker": c.speaker,
                "section_heading": c.section_heading,
            }
        )

    # Lazy import to keep this module importable without DB at parse time.
    from storage.chunk_queries import insert_chunks

    chunk_ids = await insert_chunks(
        session_id=session_id,
        blob_id=blob_id,
        source_file_id=source_file_id,
        source_type=source_kind,
        source_filename=source_filename,
        source_url=source_url,
        trust_level=trust_level or _TRUST_BY_KIND.get(source_kind, "web_general"),
        rows=rows,
    )

    return {
        "chunks_inserted": len(chunk_ids),
        "chunk_ids": chunk_ids,
        "first_chunk_meta": {
            "page": chunks[0].page,
            "slide": chunks[0].slide,
            "timestamp_str": chunks[0].timestamp_str,
            "section_heading": chunks[0].section_heading,
        },
    }
