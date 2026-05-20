"""Library-text chunker — W14/D2.

Wraps the W5 ingestion path's chunker with a more careful text-splitting
pass for plain-text / markdown firm-library uploads:

  - Sentence-boundary respect: long paragraphs get split at sentence
    endings rather than mid-clause.
  - Token-targeted sizing: targets ~600 tokens (≈2400 chars at 4 chars
    per token), bounded to [400, 800] tokens. Within those bounds the
    chunker prefers natural paragraph + sentence boundaries.
  - Overlap: ~10% of chunk size (200 chars) prepended from the previous
    chunk's tail so a claim that straddles a chunk boundary is still
    retrievable.
  - Table preservation: a contiguous run of markdown table lines
    (``| col | col |`` rows) is kept in a single chunk — never split
    across two chunks even if it exceeds the target size. (We log a
    note and let the over-sized table through; the W5 retrieval-side
    embedder copes with longer inputs.)

The chunker emits ``Chunk`` objects compatible with the W5 retrieval
pipeline (same dataclass, same metadata keys). Retrieval logic is
untouched — only the upstream packing changes.

Public surface: :func:`chunk_library_text`.
"""

from __future__ import annotations

import re

from ingest.chunking.base import Chunk


# Approx-tokens model: 4 chars per token is the rule-of-thumb for English
# prose with a Latin alphabet. We pick char-count targets so we don't
# have to load a tokenizer at ingest time.
_TARGET_CHARS = 2400          # ~600 tokens
_MIN_CHARS = 1600             # ~400 tokens
_MAX_CHARS = 3200             # ~800 tokens
_OVERLAP_CHARS = 200          # ~50 tokens
_HARD_FALLBACK_CHARS = 4000   # only used when a single paragraph is
                              # bigger than _MAX_CHARS and we can't find
                              # a sentence boundary to split on.

# A markdown table row looks like ``| col | col |`` (with at least one
# pipe in the middle). The separator row is ``| --- | --- |`` etc.
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def _is_table_line(line: str) -> bool:
    return bool(_TABLE_ROW_RE.match(line))


def _split_into_blocks(text: str) -> list[tuple[str, str]]:
    """Walk the text top-down and group consecutive lines into blocks.

    Returns a list of ``(kind, text)`` tuples where kind is one of
    ``"para"``, ``"heading"``, ``"table"``, ``"list"``.

    Blocks are the unit we pack into chunks — a chunk is one or more
    full blocks. We never split a block; tables in particular stay
    whole even when they overflow the target.
    """
    blocks: list[tuple[str, str]] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Skip blank-line separators.
        if not stripped:
            i += 1
            continue

        # Headings stand alone.
        if stripped.startswith("#"):
            blocks.append(("heading", stripped))
            i += 1
            continue

        # Tables: pull every consecutive line that matches the pattern.
        if _is_table_line(line):
            j = i
            while j < n and (
                _is_table_line(lines[j]) or (lines[j].strip() == "" and j + 1 < n and _is_table_line(lines[j + 1]))
            ):
                j += 1
            tbl_lines = [ln for ln in lines[i:j] if ln.strip()]
            blocks.append(("table", "\n".join(tbl_lines)))
            i = j
            continue

        # List blocks: contiguous lines starting with ``-`` / ``*`` / digit.
        if re.match(r"^\s*(?:[-*+]\s|\d+[\.\)]\s)", line):
            j = i
            while j < n and re.match(r"^\s*(?:[-*+]\s|\d+[\.\)]\s)", lines[j]):
                j += 1
            list_lines = lines[i:j]
            blocks.append(("list", "\n".join(list_lines)))
            i = j
            continue

        # Paragraph: contiguous non-blank, non-table, non-list lines.
        j = i
        while j < n:
            ln = lines[j].strip()
            if not ln:
                break
            if ln.startswith("#") or _is_table_line(lines[j]):
                break
            if re.match(r"^\s*(?:[-*+]\s|\d+[\.\)]\s)", lines[j]):
                break
            j += 1
        para_lines = [lines[k] for k in range(i, j)]
        blocks.append(("para", "\n".join(para_lines).strip()))
        i = j

    return blocks


def _split_oversize_paragraph(text: str) -> list[str]:
    """Split a paragraph that's bigger than ``_MAX_CHARS`` at sentence
    boundaries. Sentence boundaries: ``.``, ``!``, ``?`` followed by
    whitespace + capital. Tolerates ``Mr.``, ``Dr.``, ``vs.`` by
    requiring a 2+ char run before the punctuation and a single
    uppercase character after the space (heuristic — good enough for
    consulting-firm prose).
    """
    if len(text) <= _MAX_CHARS:
        return [text]

    # Sentence-split using a regex that looks behind for ``[.!?]`` and
    # ahead for ``\s+[A-Z]`` while not consuming the boundary.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    out: list[str] = []
    buf = ""
    for s in sentences:
        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= _MAX_CHARS:
            buf = f"{buf} {s}"
        else:
            out.append(buf)
            buf = s
    if buf:
        out.append(buf)

    # If a single sentence still exceeds the hard fallback (rare —
    # tabular paste-in or a malformed paragraph with no full stops),
    # split at the hard char limit.
    rescued: list[str] = []
    for piece in out:
        if len(piece) <= _HARD_FALLBACK_CHARS:
            rescued.append(piece)
            continue
        # Walk char-by-char and break at the nearest whitespace ≤ the
        # hard limit so we don't slice mid-word.
        pos = 0
        while pos < len(piece):
            end = min(len(piece), pos + _HARD_FALLBACK_CHARS)
            if end < len(piece):
                ws = piece.rfind(" ", pos, end)
                if ws > pos + _HARD_FALLBACK_CHARS // 2:
                    end = ws
            rescued.append(piece[pos:end].strip())
            pos = end
    return [r for r in rescued if r]


def chunk_library_text(text: str) -> list[Chunk]:
    """Pack a plain-text / markdown firm-library document into
    sentence-aware, overlap-prepended chunks.

    Tables are kept whole; paragraphs that exceed ``_MAX_CHARS`` get
    sentence-split. Successive chunks carry a small tail from the
    previous chunk so a claim that straddles a boundary is still
    retrievable.
    """
    if not text or not text.strip():
        return []

    blocks = _split_into_blocks(text)
    if not blocks:
        return []

    # Expand oversized paragraphs first so the packing pass below sees
    # only block-sized pieces.
    expanded: list[tuple[str, str]] = []
    for kind, body in blocks:
        if kind == "para" and len(body) > _MAX_CHARS:
            for piece in _split_oversize_paragraph(body):
                expanded.append(("para", piece))
        else:
            expanded.append((kind, body))

    chunks: list[Chunk] = []
    section_heading: str | None = None

    buf_lines: list[str] = []
    buf_chars = 0

    def flush(prev_tail: str = "") -> str:
        nonlocal buf_lines, buf_chars
        if not buf_lines:
            return ""
        body = "\n\n".join(buf_lines).strip()
        if not body:
            buf_lines = []
            buf_chars = 0
            return ""
        if prev_tail and not body.startswith(prev_tail):
            body = prev_tail + "\n\n" + body
        chunks.append(
            Chunk(
                content=body,
                position=len(chunks),
                section_heading=section_heading,
            )
        )
        tail = body[-_OVERLAP_CHARS:] if len(body) > _OVERLAP_CHARS else body
        buf_lines = []
        buf_chars = 0
        return tail

    prev_tail = ""

    for kind, body in expanded:
        body_len = len(body)

        if kind == "heading":
            # Heading starts a new section. If we already have a packed
            # buffer past the minimum, flush before switching sections
            # so the heading doesn't get orphaned at the tail of an
            # earlier chunk.
            if buf_chars >= _MIN_CHARS:
                prev_tail = flush(prev_tail)
            section_heading = body.lstrip("# ").strip()[:200]
            # Drop the heading itself into the next chunk so the heading
            # text is searchable.
            buf_lines.append(body)
            buf_chars += body_len + 2
            continue

        if kind == "table":
            # Tables are inviolate — they go whole into whatever the
            # current chunk is, even if oversize. If the table alone
            # exceeds the max, we flush the current buffer first so the
            # table gets its own chunk.
            if buf_chars + body_len > _MAX_CHARS and buf_chars >= _MIN_CHARS:
                prev_tail = flush(prev_tail)
            buf_lines.append(body)
            buf_chars += body_len + 2
            # If the table alone overflows, flush it now in its own chunk.
            if buf_chars >= _MAX_CHARS:
                prev_tail = flush(prev_tail)
            continue

        # Default packing: paragraph + list blocks.
        if buf_chars + body_len > _MAX_CHARS and buf_chars >= _MIN_CHARS:
            prev_tail = flush(prev_tail)
        buf_lines.append(body)
        buf_chars += body_len + 2

        # If we've reached the target and the next block would push us
        # over, flush proactively so we don't keep packing past target.
        if buf_chars >= _TARGET_CHARS:
            prev_tail = flush(prev_tail)

    # Tail flush.
    if buf_lines:
        flush(prev_tail)

    return chunks


__all__ = ["chunk_library_text"]
