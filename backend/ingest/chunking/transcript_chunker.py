"""Transcript chunker — one chunk per speaker turn (or topic boundary).

Recognizes:
  Speaker A: ...                        → chunk per turn
  [00:12:34] Speaker B: ...            → captures timestamp
  Speaker B (00:12:34): ...            → captures timestamp
  Plain timestamps on their own line   → boundary marker

Falls back to paragraph-level chunking if no speaker pattern is found.
"""

from __future__ import annotations

import re

from .base import Chunk

_SPEAKER_LINE = re.compile(
    r"^(?:\[(?P<ts1>\d{1,2}:\d{2}(?::\d{2})?)\]\s*)?"
    r"(?P<speaker>[A-Z][\w \.\-]{1,40}?)"
    r"(?:\s*\((?P<ts2>\d{1,2}:\d{2}(?::\d{2})?)\))?"
    r"\s*:\s*(?P<text>.+)$",
    re.UNICODE,
)
_BARE_TIMESTAMP = re.compile(r"^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*$")
_MIN_CHUNK_CHARS = 60


def chunk_transcript(text: str, *, max_chunk_chars: int = 1500) -> list[Chunk]:
    lines = [l for l in text.splitlines() if l.strip()]
    chunks: list[Chunk] = []

    current_speaker: str | None = None
    current_ts: str | None = None
    current_buf: list[str] = []
    position = 0

    def flush():
        nonlocal position, current_buf
        body = " ".join(current_buf).strip()
        if len(body) < _MIN_CHUNK_CHARS:
            current_buf = []
            return
        # Hard-cap; if a turn is huge, split it but keep speaker/timestamp attribution.
        chunks.append(
            Chunk(
                content=body[:max_chunk_chars],
                position=position,
                speaker=current_speaker,
                timestamp_str=current_ts,
            )
        )
        position += 1
        # If overflow, recursively split the rest.
        if len(body) > max_chunk_chars:
            tail = body[max_chunk_chars:].lstrip()
            while tail:
                chunks.append(
                    Chunk(
                        content=tail[:max_chunk_chars],
                        position=position,
                        speaker=current_speaker,
                        timestamp_str=current_ts,
                    )
                )
                position += 1
                tail = tail[max_chunk_chars:].lstrip()
        current_buf = []

    matched_any = False
    for raw in lines:
        line = raw.strip()
        m = _SPEAKER_LINE.match(line)
        if m:
            matched_any = True
            flush()
            current_speaker = (m.group("speaker") or "").strip()
            current_ts = (m.group("ts1") or m.group("ts2") or current_ts)
            current_buf = [m.group("text").strip()]
            continue
        bts = _BARE_TIMESTAMP.match(line)
        if bts:
            current_ts = bts.group(1)
            continue
        # Continuation of current turn.
        current_buf.append(line)
    flush()

    if not matched_any:
        # Fallback: paragraph chunks (blank-line separated).
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for i, p in enumerate(paragraphs):
            if len(p) < _MIN_CHUNK_CHARS:
                continue
            chunks.append(Chunk(content=p[:max_chunk_chars], position=i))

    return chunks
