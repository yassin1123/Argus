"""News ingestion helper — Tavily search → chunk → embed → insert_chunks.

Per-(engagement, query) caching: the orchestrator calls
``fetch_and_ingest_news`` for each task that declares ``"news"`` in its
``source_priorities``. We check ``chunks WHERE source_type='news' AND
session_id=$1 AND metadata->>'task_query'=$2`` first; on cache hit we
return ``cached=True`` without spending Tavily quota or embedding tokens.

Cross-engagement isolation: two different sessions hitting the same
query each pay their own Tavily call. This is intentional — different
firms / engagements run on different evidence universes by design (no
implicit cross-leak).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from core.embeddings import embed_texts
from core.retrievers.news.chunker import chunk_news_article
from core.retrievers.news.tavily_client import (
    TavilyError,
    TavilyResult,
    tavily_search,
)
from db.connection import acquire
from storage.chunk_queries import insert_chunks

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE: int = 96

# Sources whose claims we trust as primary on day one. Everything else
# starts at trust_level='general' and only gets promoted by an admin
# (Phase 4 work). Domains are stored as bare host suffixes so subdomain
# matches (e.g. www.reuters.com, edition.cnn.com) work.
TRUSTED_NEWS_DOMAINS: frozenset[str] = frozenset(
    {
        "reuters.com",
        "ft.com",
        "wsj.com",
        "bloomberg.com",
        "nytimes.com",
        "economist.com",
        "sec.gov",
        "gov.uk",
    }
)


@dataclass
class NewsIngestResult:
    """Aggregate return of :func:`fetch_and_ingest_news`."""

    cached: bool = False
    tavily_results: int = 0
    articles_chunked: int = 0
    chunks_written: int = 0
    skipped_empty: int = 0
    errors: list[str] = field(default_factory=list)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _trust_level_for(host: str) -> str:
    """Return ``firm_vetted`` for the small known-trustworthy list, else ``general``."""
    if not host:
        return "general"
    # Match against suffix so news.reuters.com still maps to reuters.com.
    for trusted in TRUSTED_NEWS_DOMAINS:
        if host == trusted or host.endswith("." + trusted):
            return "firm_vetted"
    return "general"


def _query_key(query: str) -> str:
    """Stable hash of the query for the metadata cache-key field."""
    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def has_cached_news(session_id: str, query: str) -> int:
    """Return the number of cached news chunks for this (session, query) tuple.

    Used by callers that want to know cache state without forcing a fetch.
    """
    qk = _query_key(query)
    async with acquire() as conn:
        n = await conn.fetchval(
            """
            SELECT count(*)::int FROM chunks
            WHERE source_type = 'news'
              AND session_id = $1::uuid
              AND metadata->>'task_query_hash' = $2
            """,
            session_id,
            qk,
        )
    return int(n or 0)


async def fetch_and_ingest_news(
    *,
    session_id: str,
    query: str,
    max_results: int = 10,
    days: int = 90,
    api_key: str | None = None,
) -> NewsIngestResult:
    """Run one (engagement, query) news fetch and ingest the results.

    Returns ``cached=True`` when chunks already exist for this tuple.
    Raises :class:`TavilyError` only if the caller wants to surface
    failure; the orchestrator catches and degrades, but returning the
    error gives finer control to tests.
    """
    cached_count = await has_cached_news(session_id, query)
    if cached_count > 0:
        logger.info(
            "news cache HIT for session=%s query=%r (%d chunks)",
            session_id,
            query[:80],
            cached_count,
        )
        return NewsIngestResult(cached=True, chunks_written=cached_count)

    try:
        results = await tavily_search(
            query, max_results=max_results, days=days, api_key=api_key
        )
    except TavilyError:
        # Re-raise — orchestrator decides whether to degrade or fall
        # back to SerpAPI based on its env flags.
        raise

    out = NewsIngestResult(tavily_results=len(results))
    if not results:
        return out

    qk = _query_key(query)
    # Group rows so we issue ONE insert_chunks per article (so each
    # article's chunks share an inserted-source URL and trust level).
    for art in results:
        body = art.raw_content or art.content
        if not body or len(body) < 200:
            out.skipped_empty += 1
            continue
        chunks = chunk_news_article(body)
        if not chunks:
            out.skipped_empty += 1
            continue
        out.articles_chunked += 1

        contents = [c.content for c in chunks]
        embeddings: list[list[float]] = []
        for i in range(0, len(contents), _EMBED_BATCH_SIZE):
            batch = contents[i : i + _EMBED_BATCH_SIZE]
            try:
                embeddings.extend(await embed_texts(batch))
            except Exception as e:  # noqa: BLE001
                out.errors.append(
                    f"embed failed for {art.url}: {type(e).__name__}: {e}"
                )
                embeddings = []
                break
        if not embeddings or len(embeddings) != len(chunks):
            continue

        host = _domain(art.url)
        trust = _trust_level_for(host)

        rows: list[dict[str, Any]] = []
        for pos, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            rows.append(
                {
                    "content": chunk.content,
                    "content_hash": _content_hash(chunk.content),
                    "embedding": emb,
                    "position": pos,
                    "section_heading": (art.title or host)[:200],
                    "metadata": {
                        "url": art.url,
                        "title": art.title,
                        "source_domain": host,
                        "published_date": art.published_date,
                        "tavily_score": art.score,
                        "task_query": query,
                        "task_query_hash": qk,
                        "char_offset": chunk.char_offset,
                    },
                }
            )

        try:
            written = await insert_chunks(
                session_id=session_id,
                blob_id=None,
                source_file_id=None,
                source_type="news",
                source_filename=(art.title or host)[:1024],
                source_url=art.url,
                trust_level=trust,
                rows=rows,
            )
        except Exception as e:  # noqa: BLE001
            out.errors.append(f"insert_chunks failed for {art.url}: {type(e).__name__}: {e}")
            continue
        out.chunks_written += len(written)

    logger.info(
        "news ingest session=%s query=%r tavily=%d articles=%d chunks=%d",
        session_id,
        query[:80],
        out.tavily_results,
        out.articles_chunked,
        out.chunks_written,
    )
    return out
