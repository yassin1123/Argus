"""Common chunker types."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A single retrievable unit of text from a source.

    `position` is 0-indexed within the source; only one of `page`, `slide`, or
    `timestamp_str` is typically set (the chunker fills whichever applies).
    """

    content: str
    position: int = 0
    page: int | None = None
    slide: int | None = None
    timestamp_str: str | None = None
    speaker: str | None = None
    section_heading: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.strip().encode("utf-8")).hexdigest()

    def to_meta(self) -> dict:
        """Return the chunk metadata as a dict (used by the legacy embeddings writer)."""
        return {
            "chunk_index": self.position,
            "page": self.page,
            "slide": self.slide,
            "timestamp": self.timestamp_str,
            "speaker": self.speaker,
            "section_hint": self.section_heading,
            **(self.extra or {}),
        }
