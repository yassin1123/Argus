"""Manual-upload ingestion for earnings-call transcripts.

Imported by both ``tools/transcript_upload.py`` (CLI) and
``tests/test_transcripts_ingest.py``. Kept inside ``backend/`` so the
test suite can import without sys.path gymnastics.

VTT / SRT detection + normalisation lives here too: cue indexes and
timestamp lines are stripped, and inline ``<v Name>...</v>`` speaker
tags are converted to the bare ``Name: text`` form the chunker
recognises.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from core.embeddings import embed_texts
from core.retrievers.transcripts.chunker import chunk_transcript
from storage.chunk_queries import insert_chunks

_EMBED_BATCH_SIZE: int = 96

_VTT_HEADER_RE = re.compile(r"^WEBVTT\b", re.IGNORECASE | re.MULTILINE)
_VTT_TIMESTAMP_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}",
    re.MULTILINE,
)
_SRT_INDEX_RE = re.compile(r"^\d+\s*$", re.MULTILINE)


def _content_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def normalise_vtt_or_srt(raw: str) -> str:
    """Strip cue-numbering + timestamp lines from VTT/SRT, joining text lines.

    Speaker labels embedded in cues (e.g. ``<v Tim Cook>X</v>`` in VTT)
    survive — converted to ``Tim Cook: X`` so the chunker picks them up.
    """
    out_lines: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            out_lines.append("")
            continue
        if s.upper().startswith("WEBVTT"):
            continue
        if _VTT_TIMESTAMP_RE.match(s):
            continue
        if _SRT_INDEX_RE.match(s):
            continue
        s = re.sub(r"<v\s+([^>]+)>", r"\1: ", s, flags=re.IGNORECASE)
        s = re.sub(r"</v>", "", s, flags=re.IGNORECASE)
        s = re.sub(r"<[^>]+>", "", s)
        out_lines.append(s)
    text = "\n".join(out_lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def detect_input_shape(text: str, path: Path) -> str:
    """Return ``'vtt'``, ``'srt'``, or ``'text'`` (per content, not extension)."""
    if _VTT_HEADER_RE.search(text):
        return "vtt"
    if _VTT_TIMESTAMP_RE.search(text) and path.suffix.lower() == ".vtt":
        return "vtt"
    if path.suffix.lower() == ".srt" and _SRT_INDEX_RE.search(text):
        return "srt"
    if _VTT_TIMESTAMP_RE.search(text):
        return "srt"
    return "text"


def load_and_normalise(path: Path) -> tuple[str, str]:
    """Return ``(shape, normalised_text)`` from a TXT/VTT/SRT file."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    shape = detect_input_shape(raw, path)
    if shape in ("vtt", "srt"):
        return shape, normalise_vtt_or_srt(raw)
    return shape, raw.strip()


async def ingest_manual_transcript(
    *,
    text: str,
    ticker: str,
    company_name: str,
    quarter: str,
    year: int,
    source_label: str,
    source_path: Path,
    session_id: str | None,
    trust_level: str = "general",
) -> dict[str, Any]:
    """Chunk, embed, write. Returns counts + provenance for the CLI summary.

    Idempotency keyed on a synthetic ``MANUAL-<hash>`` accession_number
    derived from (ticker, quarter, year, content head) so re-running on
    the same transcript doesn't double-write.
    """
    chunks = chunk_transcript(text)
    if not chunks:
        return {"chunks_written": 0, "error": "chunker produced zero chunks"}

    contents = [c.content for c in chunks]
    embeddings: list[list[float]] = []
    for i in range(0, len(contents), _EMBED_BATCH_SIZE):
        batch = contents[i : i + _EMBED_BATCH_SIZE]
        embeddings.extend(await embed_texts(batch))
    if len(embeddings) != len(chunks):
        return {
            "chunks_written": 0,
            "error": f"embedding count mismatch: {len(embeddings)} vs {len(chunks)}",
        }

    pseudo_accession = "MANUAL-" + _content_hash(
        f"{ticker}|{quarter}|{year}|{text[:8192]}"
    )[:18].upper()

    rows: list[dict[str, Any]] = []
    for pos, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        metadata = {
            "ticker": ticker,
            "company_name": company_name,
            "quarter": quarter,
            "year": int(year),
            "source": source_label,
            "speaker": chunk.speaker,
            "role": chunk.role,
            "firm": chunk.firm,
            "segment": chunk.segment,
            "turn_index": chunk.turn_index,
            "char_offset_in_transcript": chunk.char_offset_in_transcript,
            "accession_number": pseudo_accession,
            "uploaded_filename": source_path.name,
        }
        rows.append(
            {
                "content": chunk.content,
                "content_hash": _content_hash(chunk.content),
                "embedding": emb,
                "position": pos,
                "section_heading": (
                    f"{chunk.segment} · {chunk.speaker}" if chunk.speaker else chunk.segment
                ),
                "metadata": metadata,
            }
        )

    source_filename = f"Earnings call · {ticker} {quarter} FY{year}"
    written = await insert_chunks(
        session_id=session_id,
        blob_id=None,
        source_file_id=None,
        source_type="transcript",
        source_filename=source_filename,
        source_url=None,
        trust_level=trust_level,
        rows=rows,
    )
    return {
        "chunks_written": len(written),
        "pseudo_accession": pseudo_accession,
        "ticker": ticker,
        "quarter": quarter,
        "year": year,
        "speakers": sorted({c.speaker for c in chunks if c.speaker}),
    }
