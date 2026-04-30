"""PDF chunker — page + heading aware.

For each page, detect headings using PyMuPDF font metadata (size or bold flag
above the page-median baseline). Splits the page into sections under each
heading. If no headings are found on a page, the whole page becomes one chunk.

Falls back gracefully if PyMuPDF can't open the file.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

import fitz  # PyMuPDF

from .base import Chunk

logger = logging.getLogger(__name__)

# Treat a span as a heading if its font size is at least this multiple of the
# page-median size, OR if the bold flag is set and the size is above the median.
_HEADING_SIZE_RATIO = 1.18

# Skip very short fragments (likely page numbers, headers/footers).
_MIN_CHUNK_CHARS = 60


def _extract_page_blocks(page: "fitz.Page") -> list[dict[str, Any]]:
    """Pull text spans with font metadata from a page."""
    out: list[dict[str, Any]] = []
    try:
        blocks = page.get_text("dict").get("blocks", [])  # type: ignore[arg-type]
    except Exception:
        return []
    for block in blocks:
        if block.get("type", 0) != 0:  # 0 = text block
            continue
        for line in block.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not line_text:
                continue
            spans = line.get("spans", [])
            sizes = [float(s.get("size", 0)) for s in spans if s.get("size")]
            flags = [int(s.get("flags", 0)) for s in spans]
            avg_size = sum(sizes) / len(sizes) if sizes else 0.0
            is_bold = any((f & 16) or (f & 2) for f in flags)  # 16=bold-ish flag
            out.append(
                {
                    "text": line_text,
                    "size": avg_size,
                    "bold": is_bold,
                    "y": float(line.get("bbox", (0, 0, 0, 0))[1]),
                }
            )
    return out


def _is_heading(line: dict[str, Any], median_size: float) -> bool:
    if median_size <= 0:
        return False
    size = line["size"]
    if size >= median_size * _HEADING_SIZE_RATIO:
        return True
    if line["bold"] and size >= median_size * 1.05:
        # Bold + slightly larger → still a heading.
        return True
    # Short uppercase line is also heading-like.
    txt = line["text"]
    if line["bold"] and len(txt) <= 80 and txt == txt.upper():
        return True
    return False


def chunk_pdf(content: bytes, *, max_chunk_chars: int = 1200) -> list[Chunk]:
    chunks: list[Chunk] = []
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        logger.warning("PDF open failed: %s", e)
        return chunks

    position = 0
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        page_no = page_index + 1
        lines = _extract_page_blocks(page)
        if not lines:
            continue

        sizes = [l["size"] for l in lines if l["size"] > 0]
        median_size = statistics.median(sizes) if sizes else 0.0

        # Walk the page accumulating text under each heading.
        current_section: str | None = None
        current_buf: list[str] = []

        def flush():
            nonlocal position, current_buf
            text = "\n".join(current_buf).strip()
            if len(text) >= _MIN_CHUNK_CHARS:
                # Hard-cap chunk size — if a page section is huge, split.
                for piece in _split_long(text, max_chunk_chars):
                    chunks.append(
                        Chunk(
                            content=piece,
                            position=position,
                            page=page_no,
                            section_heading=current_section,
                        )
                    )
                    position += 1
            current_buf = []

        for line in lines:
            if _is_heading(line, median_size):
                flush()
                current_section = line["text"]
            else:
                current_buf.append(line["text"])
        flush()

    doc.close()

    # If section detection produced nothing, fall back to one chunk per page.
    if not chunks:
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            for page_index in range(doc.page_count):
                text = doc.load_page(page_index).get_text("text").strip()
                if len(text) >= _MIN_CHUNK_CHARS:
                    for piece in _split_long(text, max_chunk_chars):
                        chunks.append(
                            Chunk(
                                content=piece,
                                position=len(chunks),
                                page=page_index + 1,
                            )
                        )
            doc.close()
        except Exception:
            pass

    return chunks


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    buf = ""
    for p in paragraphs:
        if not buf:
            buf = p
        elif len(buf) + 1 + len(p) <= max_chars:
            buf = f"{buf}\n{p}"
        else:
            out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    return out
