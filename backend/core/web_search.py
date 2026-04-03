import asyncio
import os
from typing import Any

import httpx

from core.research_utils import normalize_url

SERPAPI_KEY = os.getenv("SERPAPI_KEY")


async def search_web_structured(query: str, num_results: int = 5) -> list[dict[str, Any]]:
    """SerpAPI organic results as dicts (title, url, snippet, position)."""
    if not SERPAPI_KEY:
        return []
    params = {
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": num_results,
        "engine": "google",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get("https://serpapi.com/search", params=params)
        response.raise_for_status()
        data = response.json()
    out: list[dict[str, Any]] = []
    for i, result in enumerate(data.get("organic_results", [])[:num_results]):
        date_str = str(result.get("date") or "")[:80]
        out.append(
            {
                "title": str(result.get("title") or "")[:500],
                "url": str(result.get("link") or "")[:2000],
                "snippet": str(result.get("snippet") or "")[:1500],
                "position": int(result.get("position") or i + 1),
                "date": date_str,
            }
        )
    return out


async def search_web_parallel(queries: list[str], num_results: int = 4) -> list[dict[str, Any]]:
    """Run structured searches in parallel; dedupe by URL."""
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
    if not SERPAPI_KEY:
        return "Web search not available (no API key configured)"
    params = {
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": num_results,
        "engine": "google",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get("https://serpapi.com/search", params=params)
        response.raise_for_status()
        data = response.json()
    results = []
    for result in data.get("organic_results", [])[:num_results]:
        results.append(
            f"Title: {result.get('title')}\nSnippet: {result.get('snippet')}\nURL: {result.get('link')}"
        )
    return "\n\n".join(results) if results else "No organic results returned."
