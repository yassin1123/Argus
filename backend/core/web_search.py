"""Web search adapter — Tavily-first, with optional fallbacks.

Provider selection (highest priority first):
  1. TAVILY_API_KEY — Tavily Search API. Day 3's primary backend
     because it returns full extracted page text (``raw_content``)
     which the verifier needs for NLI grounding. Snippet-only providers
     (Brave / SerpAPI) only return ~150 chars of text per result, so
     ensemble verdicts on those degrade to "weak" by structural
     constraint.
  2. BRAVE_API_KEY — Brave Web Search API. Snippet-only.
  3. SERPAPI_KEY — SerpAPI (Google). Snippet-only. Disabled by default
     in Day 3+ (snippet-only sources hurt verifier output); only
     activates when ``ARGUS_NEWS_FALLBACK_TO_SERPAPI=true``.

All backends normalise to the same dict shape so the rest of the
pipeline doesn't care which one is in use:
    {title, url, snippet, position, date}

Returns ``[]`` when no provider is configured or any HTTP error
occurs, so the research stage can degrade gracefully.
"""

import asyncio
import logging
import os
from typing import Any

import httpx

from core.research_utils import normalize_url

logger = logging.getLogger(__name__)


def _clean_key(raw: str | None) -> str:
    """Strip whitespace and trailing inline comments (`#...`) from an env value."""
    if not raw:
        return ""
    return raw.split("#", 1)[0].strip()


SERPAPI_KEY = _clean_key(os.getenv("SERPAPI_KEY"))
BRAVE_API_KEY = _clean_key(os.getenv("BRAVE_API_KEY"))


def _serpapi_fallback_enabled() -> bool:
    """``ARGUS_NEWS_FALLBACK_TO_SERPAPI=true`` opts the SerpAPI path back in.

    Default false (Day 3): snippet-only providers degrade verifier output
    so we'd rather return zero web results than a degraded set.
    """
    raw = os.getenv("ARGUS_NEWS_FALLBACK_TO_SERPAPI", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _active_provider() -> str:
    # Read the Tavily key lazily so tests can flip the env var via
    # monkeypatch without re-importing the module.
    from core.retrievers.news.tavily_client import TAVILY_API_KEY  # noqa: WPS433

    if TAVILY_API_KEY:
        return "tavily"
    if BRAVE_API_KEY:
        return "brave"
    if SERPAPI_KEY and _serpapi_fallback_enabled():
        return "serpapi"
    return "none"


async def _search_brave(query: str, num_results: int) -> list[dict[str, Any]]:
    """Brave Web Search → normalized dicts. Returns [] on any error."""
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    params: dict[str, Any] = {
        "q": query,
        "count": min(max(num_results, 1), 20),  # Brave caps at 20
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, httpx.TimeoutException, ValueError):
        return []
    web = data.get("web") or {}
    results = web.get("results") or []
    out: list[dict[str, Any]] = []
    for i, result in enumerate(results[:num_results]):
        out.append(
            {
                "title": str(result.get("title") or "")[:500],
                "url": str(result.get("url") or "")[:2000],
                # Brave calls the snippet "description"
                "snippet": str(result.get("description") or "")[:1500],
                "position": i + 1,
                # `page_age` is ISO-ish when present; fall back to `age` (relative).
                "date": str(result.get("page_age") or result.get("age") or "")[:80],
            }
        )
    return out


async def _search_serpapi(query: str, num_results: int) -> list[dict[str, Any]]:
    """SerpAPI organic results → normalized dicts. Returns [] on any error."""
    params = {
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": num_results,
        "engine": "google",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get("https://serpapi.com/search", params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, httpx.TimeoutException, ValueError):
        return []
    out: list[dict[str, Any]] = []
    for i, result in enumerate(data.get("organic_results", [])[:num_results]):
        out.append(
            {
                "title": str(result.get("title") or "")[:500],
                "url": str(result.get("link") or "")[:2000],
                "snippet": str(result.get("snippet") or "")[:1500],
                "position": int(result.get("position") or i + 1),
                "date": str(result.get("date") or "")[:80],
            }
        )
    return out


async def _search_tavily(query: str, num_results: int) -> list[dict[str, Any]]:
    """Tavily → normalized dicts. Returns ``[]`` on error.

    Tavily's ``content`` field maps to the legacy ``snippet`` so existing
    triage scoring keeps working. Tavily also returns ``raw_content``
    (full page text) but the legacy callers don't use it — the
    chunked-news path lives in
    ``core.retrievers.news.fetch_and_ingest_news`` and reads it
    directly. This function is for the legacy gap-fill paths only.
    """
    from core.retrievers.news.tavily_client import (  # noqa: WPS433
        TavilyError,
        tavily_search,
    )

    try:
        results = await tavily_search(query, max_results=max(num_results, 1))
    except TavilyError as e:
        logger.warning("Tavily structured search failed for %r: %s", query, e)
        return []
    out: list[dict[str, Any]] = []
    for i, r in enumerate(results[:num_results]):
        out.append(
            {
                "title": r.title[:500],
                "url": r.url[:2000],
                "snippet": (r.content or "")[:1500],
                "position": i + 1,
                "date": r.published_date[:80],
            }
        )
    return out


async def search_web_structured(query: str, num_results: int = 5) -> list[dict[str, Any]]:
    """Structured web results.

    Provider order: Tavily → Brave → SerpAPI (only with
    ``ARGUS_NEWS_FALLBACK_TO_SERPAPI=true``). Returns ``[]`` when nothing
    is configured.
    """
    provider = _active_provider()
    if provider == "tavily":
        return await _search_tavily(query, num_results)
    if provider == "brave":
        return await _search_brave(query, num_results)
    if provider == "serpapi":
        return await _search_serpapi(query, num_results)
    return []


async def search_web_parallel(queries: list[str], num_results: int = 4) -> list[dict[str, Any]]:
    """Run structured searches in parallel; dedupe by normalized URL."""
    if not queries:
        return []
    tasks = [search_web_structured(q.strip(), num_results=num_results) for q in queries if q.strip()]
    if not tasks:
        return []
    groups = await asyncio.gather(*tasks, return_exceptions=True)
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for g in groups:
        if isinstance(g, Exception):
            continue
        for item in g:
            url = (item.get("url") or "").strip()
            key = normalize_url(url) if url else ""
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


async def search_web(query: str, num_results: int = 5) -> str:
    """Plain-text variant for legacy callers; same provider auto-selection."""
    provider = _active_provider()
    if provider == "none":
        return "Web search not available (no API key configured)"
    rows = await search_web_structured(query, num_results=num_results)
    if not rows:
        return "No organic results returned."
    return "\n\n".join(
        f"Title: {r.get('title')}\nSnippet: {r.get('snippet')}\nURL: {r.get('url')}"
        for r in rows
    )
