"""Web / HTML / generic-text chunker — heading-aware.

Strategy:
  - If input looks like HTML, parse with BeautifulSoup and split on h1/h2/h3.
  - Otherwise treat as plain text: split on blank lines into paragraphs,
    recombine until each chunk is ~max_chunk_chars.

Each chunk carries the nearest preceding heading as `section_heading`.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from .base import Chunk

_MIN_CHUNK_CHARS = 80


def _is_html(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith("<!doctype") or head.startswith("<html") or "</p>" in head or "</body>" in head


def _walk_html(soup: BeautifulSoup) -> list[tuple[str | None, str]]:
    """Return list of (section_heading, text) groups."""
    groups: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    current_buf: list[str] = []

    def flush():
        text = "\n".join(p.strip() for p in current_buf if p.strip()).strip()
        if text:
            groups.append((current_heading, text))

    body: Any = soup.body or soup
    for el in body.descendants:
        if not isinstance(el, Tag):
            continue
        name = (el.name or "").lower()
        if name in ("h1", "h2", "h3"):
            flush()
            current_buf = []
            current_heading = el.get_text(" ", strip=True)[:200] or current_heading
        elif name in ("p", "li", "blockquote", "pre"):
            txt = el.get_text(" ", strip=True)
            if txt:
                current_buf.append(txt)
    flush()
    return groups


def chunk_web(text: str, *, max_chunk_chars: int = 1200) -> list[Chunk]:
    chunks: list[Chunk] = []
    if not text or not text.strip():
        return chunks

    if _is_html(text):
        try:
            soup = BeautifulSoup(text, "html.parser")
        except Exception:
            soup = None
        if soup is not None:
            for heading, body in _walk_html(soup):
                for piece in _split_long(body, max_chunk_chars):
                    if len(piece) < _MIN_CHUNK_CHARS:
                        continue
                    chunks.append(
                        Chunk(
                            content=piece,
                            position=len(chunks),
                            section_heading=heading,
                        )
                    )
            if chunks:
                return chunks

    # Plain text fallback: split into paragraphs by blank line, then pack.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return chunks
    buf = ""
    for p in paragraphs:
        if not buf:
            buf = p
        elif len(buf) + 1 + len(p) <= max_chunk_chars:
            buf = f"{buf}\n{p}"
        else:
            if len(buf) >= _MIN_CHUNK_CHARS:
                chunks.append(Chunk(content=buf, position=len(chunks)))
            buf = p
    if buf and len(buf) >= _MIN_CHUNK_CHARS:
        chunks.append(Chunk(content=buf, position=len(chunks)))
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
