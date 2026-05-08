"""News-article chunker.

Two stages:

1. **Boilerplate strip** — Tavily's ``raw_content`` is best-effort
   extracted text but still includes navbars, cookie banners, "Related
   articles" widgets, share-button captions, and footer links. We do
   one cheap clean-up pass with BeautifulSoup (already a dep) plus a
   "longest contiguous paragraph block" heuristic. trafilatura would do
   this better but isn't installed; the bs4 fallback is intentionally
   minimal — overaggressive stripping risks losing the actual article
   body.

2. **Paragraph chunking** — target 1500 chars with 150-char overlap,
   paragraph-aware (never splits mid-paragraph unless a single paragraph
   exceeds the target). Same shape as the EDGAR chunker so the rest of
   the pipeline doesn't need to know which retriever produced the chunk.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)

DEFAULT_TARGET_CHUNK_CHARS: int = 1500
DEFAULT_OVERLAP_CHARS: int = 150

# Selectors for nodes that almost never carry article body text. We
# remove these before extracting paragraphs.
_BOILERPLATE_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "noscript",
    "iframe",
)
# Class/id substring tells. We match on lowercase substrings so we
# don't have to enumerate every framework's naming convention.
_BOILERPLATE_CLASS_SUBSTRINGS: tuple[str, ...] = (
    "cookie",
    "consent",
    "subscribe",
    "newsletter",
    "share",
    "social",
    "related",
    "recommended",
    "comments",
    "advert",
    "promo",
    "sidebar",
)

_PARA_MIN_CHARS: int = 80  # paragraph shorter than this is dropped as boilerplate
_LARGEST_BLOCK_KEEP_RATIO: float = 0.5  # keep paragraphs ≥ this fraction of the largest

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class NewsChunk:
    """One chunk emitted by :func:`chunk_news_article`."""

    content: str
    char_offset: int  # offset in the cleaned-paragraph stream, useful for debugging


# ---------------------------------------------------------------------------
# Boilerplate strip
# ---------------------------------------------------------------------------


def _strip_html_to_paragraphs(raw_html: str) -> list[str]:
    """Best-effort article-body extraction from raw HTML.

    Returns a list of paragraph strings. Empty list when nothing usable
    is found. Uses BeautifulSoup with the lxml parser (already a dep).
    """
    try:
        from bs4 import BeautifulSoup  # noqa: WPS433
    except ImportError:
        # bs4 missing — fall back to plain regex strip.
        text = re.sub(r"<[^>]+>", " ", raw_html or "")
        text = _WHITESPACE_RE.sub(" ", text).strip()
        return [text] if text else []

    try:
        soup = BeautifulSoup(raw_html or "", "lxml")
    except Exception:
        soup = BeautifulSoup(raw_html or "", "html.parser")

    # Drop obvious-boilerplate tags entirely.
    for tag in _BOILERPLATE_TAGS:
        for el in soup.find_all(tag):
            el.decompose()

    # Drop elements whose class/id contains a boilerplate substring.
    for el in list(soup.find_all(True)):
        cls_attr = el.get("class") or []
        cls_str = " ".join(str(c) for c in cls_attr).lower()
        id_str = str(el.get("id") or "").lower()
        joined = f"{cls_str} {id_str}"
        if any(sub in joined for sub in _BOILERPLATE_CLASS_SUBSTRINGS):
            el.decompose()

    # Pull paragraph-shaped nodes. <p> is the high-signal source; <li>
    # and <blockquote> sometimes carry actual prose. We deliberately
    # don't pull bare <div> text — that's where the noise lives.
    paragraphs: list[str] = []
    for tag_name in ("p", "blockquote", "li"):
        for el in soup.find_all(tag_name):
            txt = el.get_text(" ", strip=True)
            txt = _WHITESPACE_RE.sub(" ", txt)
            if len(txt) >= _PARA_MIN_CHARS:
                paragraphs.append(txt)
    return paragraphs


def _from_plain_text(raw: str) -> list[str]:
    """Already-extracted text path — split on blank lines, drop empties."""
    parts = re.split(r"\n\s*\n", raw or "")
    out: list[str] = []
    for p in parts:
        cleaned = _WHITESPACE_RE.sub(" ", p).strip()
        if len(cleaned) >= _PARA_MIN_CHARS:
            out.append(cleaned)
    return out


def _looks_like_html(text: str) -> bool:
    if not text:
        return False
    head = text[:512].lower()
    return "<html" in head or "<body" in head or "<p>" in head or "<div" in head


def _filter_largest_block(paragraphs: list[str]) -> list[str]:
    """Heuristic: drop paragraphs much shorter than the longest one.

    News article body paragraphs cluster around 200–600 chars; sidebar
    "Read more" links are 50–120 chars. The threshold is the largest
    paragraph's length × ``_LARGEST_BLOCK_KEEP_RATIO``. This is crude
    but effective for the eight or so news-domain shapes we see in
    practice. trafilatura would do better; this is the bs4 fallback.
    """
    if not paragraphs:
        return []
    longest = max(len(p) for p in paragraphs)
    threshold = max(_PARA_MIN_CHARS, int(longest * _LARGEST_BLOCK_KEEP_RATIO))
    return [p for p in paragraphs if len(p) >= threshold]


# ---------------------------------------------------------------------------
# Paragraph chunking
# ---------------------------------------------------------------------------


def _pack_paragraphs(
    paragraphs: Iterable[str],
    *,
    target_chunk_chars: int,
    overlap_chars: int,
) -> list[NewsChunk]:
    """Pack paragraphs into chunks aiming for ``target_chunk_chars``.

    Never splits a paragraph unless it's solo-larger than the target
    (rare in news; happens in long-form features). Re-uses the EDGAR
    chunker's pattern: when a chunk fills, carry the tail-overlap into
    the next chunk's prefix so claim-spanning sentences aren't lost at
    boundaries.
    """
    chunks: list[NewsChunk] = []
    buf: list[str] = []
    buf_len = 0
    cur_offset = 0
    char_pos = 0

    def _flush() -> None:
        nonlocal buf, buf_len
        if not buf:
            return
        body = "\n\n".join(buf).strip()
        if body:
            chunks.append(NewsChunk(content=body, char_offset=cur_offset))
        buf = []
        buf_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if not buf:
            cur_offset = char_pos
        if len(para) > target_chunk_chars and not buf:
            # Solo paragraph bigger than target — emit on its own.
            chunks.append(NewsChunk(content=para, char_offset=char_pos))
            char_pos += len(para) + 2
            continue
        prospective = buf_len + len(para) + (2 if buf else 0)
        if prospective > target_chunk_chars and buf:
            _flush()
            # Carry tail-overlap into the next buffer.
            if overlap_chars > 0 and chunks:
                tail = chunks[-1].content[-overlap_chars:]
                buf.append(tail)
                buf_len = len(tail)
                cur_offset = char_pos - len(tail)
            buf.append(para)
            buf_len += len(para) + (2 if len(buf) > 1 else 0)
        else:
            buf.append(para)
            buf_len = prospective
        char_pos += len(para) + 2
    _flush()
    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chunk_news_article(
    raw: str,
    *,
    target_chunk_chars: int = DEFAULT_TARGET_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[NewsChunk]:
    """Strip boilerplate from a news article and return chunked paragraphs.

    Accepts either raw HTML or already-extracted text — detected per
    content. Returns ``[]`` when the article appears empty or pure
    boilerplate.
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    if _looks_like_html(raw):
        paragraphs = _strip_html_to_paragraphs(raw)
    else:
        paragraphs = _from_plain_text(raw)
    paragraphs = _filter_largest_block(paragraphs)
    if not paragraphs:
        return []
    return _pack_paragraphs(
        paragraphs,
        target_chunk_chars=target_chunk_chars,
        overlap_chars=overlap_chars,
    )
