"""Tavily Search API client (Week 4 / Day 3).

Endpoint: ``POST https://api.tavily.com/search``.
We always pass ``include_raw_content=True`` because the verifier needs
the full passage (not just a snippet) to ground claims with NLI.

Failure mode: any HTTPError / timeout / parse error raises
:class:`TavilyError`. We do NOT silently fall back to SerpAPI from this
module — that's the orchestrator's call, gated behind
``ARGUS_NEWS_FALLBACK_TO_SERPAPI=true`` per Day 3 spec hard rules.

Rate-limit awareness: Tavily's free tier is 1000 requests/month. The
Day 3 design fires per (engagement, query) and caches in the chunks
table afterwards, so a typical engagement consumes 1–3 requests across
its research tasks.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def _clean_key(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.split("#", 1)[0].strip()


TAVILY_API_KEY: str = _clean_key(os.getenv("TAVILY_API_KEY"))
TAVILY_ENDPOINT: str = "https://api.tavily.com/search"
DEFAULT_DAYS: int = 90
DEFAULT_MAX_RESULTS: int = 10
DEFAULT_TIMEOUT_SECONDS: float = 30.0


class TavilyError(RuntimeError):
    """Raised when Tavily fails (HTTP error, timeout, malformed response)."""


@dataclass(frozen=True)
class TavilyResult:
    """One result row from Tavily.

    ``raw_content`` is Tavily's extracted page text — strip-of-boilerplate
    is downstream (``core.retrievers.news.chunker``). When Tavily returns
    a result without raw_content (some sites block crawlers, some are
    PDFs, etc.) ``raw_content`` is empty and the chunker falls back to
    the snippet/content field.
    """

    url: str
    title: str
    content: str  # Tavily's snippet / summary
    raw_content: str  # full extracted page text (may be "")
    score: float
    published_date: str  # ISO string when present, "" otherwise


def tavily_available() -> bool:
    """Whether the dev / prod env has TAVILY_API_KEY set."""
    return bool(TAVILY_API_KEY)


def _parse(payload: dict[str, Any]) -> list[TavilyResult]:
    rows = payload.get("results")
    if not isinstance(rows, list):
        return []
    out: list[TavilyResult] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url") or "").strip()
        if not url:
            continue
        out.append(
            TavilyResult(
                url=url[:2000],
                title=str(r.get("title") or "")[:500],
                content=str(r.get("content") or "")[:2000],
                raw_content=str(r.get("raw_content") or ""),
                score=float(r.get("score") or 0.0),
                published_date=str(r.get("published_date") or "")[:64],
            )
        )
    return out


async def tavily_search(
    query: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    days: int = DEFAULT_DAYS,
    search_depth: str = "advanced",
    include_raw_content: bool = True,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    api_key: str | None = None,
) -> list[TavilyResult]:
    """Run one Tavily search and return parsed ``TavilyResult`` rows.

    Raises :class:`TavilyError` on any failure (HTTP, timeout, parse).
    Returns ``[]`` for queries that legitimately have no results — that's
    not an error.
    """
    key = (api_key or TAVILY_API_KEY).strip()
    if not key:
        raise TavilyError("TAVILY_API_KEY is not set")
    q = (query or "").strip()
    if not q:
        raise TavilyError("empty query")
    body = {
        "api_key": key,
        "query": q,
        "search_depth": search_depth,
        "max_results": int(max_results),
        "include_raw_content": bool(include_raw_content),
        "days": int(days),
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(TAVILY_ENDPOINT, json=body)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        raise TavilyError(
            f"Tavily HTTP {e.response.status_code} for query={q!r}: "
            f"{(e.response.text or '')[:300]}"
        ) from e
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        raise TavilyError(f"Tavily transport error for query={q!r}: {e}") from e
    except ValueError as e:
        raise TavilyError(f"Tavily returned non-JSON for query={q!r}: {e}") from e
    return _parse(data)
