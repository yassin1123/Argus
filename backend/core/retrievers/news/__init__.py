"""News retrieval (Phase 1 / Week 4 / Day 3).

Tavily-backed search + paragraph-aware chunking + per-engagement caching.
Web/news content gets the same first-class treatment as SEC filings:
chunked, embedded, indexed in the ``chunks`` table with
``source_type='news'``, hybrid-retrieved alongside other source types,
and run through the ensemble verifier (LLM + DeBERTa + lexical) — no
special-casing.

Public API:
  - :func:`tavily_search` — direct Tavily wrapper, returns parsed results.
  - :func:`fetch_and_ingest_news` — end-to-end: search → chunk → embed →
    insert into ``chunks``. Per-(engagement, query) idempotency.
"""

from core.retrievers.news.chunker import chunk_news_article
from core.retrievers.news.ingest import (
    TRUSTED_NEWS_DOMAINS,
    NewsIngestResult,
    fetch_and_ingest_news,
    has_cached_news,
)
from core.retrievers.news.tavily_client import (
    TAVILY_API_KEY,
    TavilyError,
    TavilyResult,
    tavily_available,
    tavily_search,
)

__all__ = [
    "TAVILY_API_KEY",
    "TRUSTED_NEWS_DOMAINS",
    "NewsIngestResult",
    "TavilyError",
    "TavilyResult",
    "chunk_news_article",
    "fetch_and_ingest_news",
    "has_cached_news",
    "tavily_available",
    "tavily_search",
]
