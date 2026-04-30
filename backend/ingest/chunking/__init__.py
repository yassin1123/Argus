"""Chunker dispatch by source type.

Each chunker returns a list of `Chunk` objects. The ingest pipeline embeds them,
persists to `chunks`, and (for backward compat) to the legacy `embeddings` table.
"""

from __future__ import annotations

from typing import Literal

from .base import Chunk
from .pdf_chunker import chunk_pdf
from .transcript_chunker import chunk_transcript
from .web_chunker import chunk_web

SourceKind = Literal["pdf", "transcript", "web", "csv", "json", "knowledge"]


def chunk_source(*, source_kind: SourceKind, content: bytes | str, **kwargs) -> list[Chunk]:
    """Dispatch to the right chunker. `content` is bytes for PDF, str otherwise."""
    if source_kind == "pdf":
        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("PDF chunker requires bytes")
        return chunk_pdf(bytes(content), **kwargs)
    if source_kind == "transcript":
        text = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else content
        return chunk_transcript(text, **kwargs)
    if source_kind in ("web", "csv", "json", "knowledge"):
        text = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else content
        return chunk_web(text, **kwargs)
    raise ValueError(f"Unknown source kind: {source_kind}")


__all__ = ["Chunk", "SourceKind", "chunk_source", "chunk_pdf", "chunk_transcript", "chunk_web"]
