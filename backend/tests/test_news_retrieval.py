"""Tavily news retrieval tests (Week 4 / Day 3).

Pin the four contracts the spec named:

  1. Tavily search returns chunked rows that flow through to the
     ``chunks`` table with the right metadata.
  2. Per-(engagement, query) caching: same engagement + same query
     reuses chunks; different engagement triggers a fresh fetch.
  3. Trusted news domains map to ``trust_level='firm_vetted'``;
     everything else maps to ``'general'``.
  4. SerpAPI is gated behind ``ARGUS_NEWS_FALLBACK_TO_SERPAPI=true``.
     When Tavily fails and the fallback flag is off, ``search_web_*``
     returns ``[]`` rather than silently falling back.

All tests stub the Tavily HTTP call and the DB write so they run
hermetically — no real API key required.
"""

from __future__ import annotations

import pytest

from core.retrievers.news import ingest as ingest_module
from core.retrievers.news.chunker import chunk_news_article
from core.retrievers.news.ingest import (
    TRUSTED_NEWS_DOMAINS,
    fetch_and_ingest_news,
)
from core.retrievers.news.tavily_client import TavilyError, TavilyResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tavily_row(
    *,
    url: str,
    title: str = "headline",
    content: str = "snippet",
    raw_content: str = "",
    score: float = 0.5,
    published_date: str = "2026-04-30",
) -> TavilyResult:
    return TavilyResult(
        url=url,
        title=title,
        content=content,
        raw_content=raw_content,
        score=score,
        published_date=published_date,
    )


def _long_article(headline: str, n_paragraphs: int = 6) -> str:
    """Build a body long enough that the chunker won't drop it as boilerplate."""
    return "\n\n".join(
        [
            headline,
            *[
                "Apple posted record September-quarter revenue of $94.9 billion, "
                f"up six percent year over year, in part driven by strong iPhone "
                f"and Services performance. Paragraph {i} continues with detail "
                "on segment performance, regional splits, and gross margin. "
                "The company guided December-quarter revenue to grow at low to "
                "mid single digits. Analysts noted the call was upbeat on "
                "Apple Intelligence demand drivers."
                for i in range(n_paragraphs)
            ],
        ]
    )


@pytest.fixture
def stub_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """1536-dim deterministic vector per text — no OpenAI call."""
    import hashlib

    async def _stub(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            full = (h * (1536 // len(h) + 1))[:1536]
            out.append([(b - 128) / 128.0 for b in full])
        return out

    monkeypatch.setattr(ingest_module, "embed_texts", _stub)


@pytest.fixture
def stub_db(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Replace the DB layer with in-memory state.

    Two methods are stubbed:
      - ``has_cached_news`` reads from the in-memory ``inserts`` list
      - ``insert_chunks`` appends to the same list

    The test asserts on cache hits / misses by counting the inserts.
    """
    state: dict = {"inserts": [], "tavily_calls": []}

    async def _stub_has_cached(session_id: str, query: str) -> int:
        # cache key = (session_id, query) — same as production logic
        from core.retrievers.news.ingest import _query_key

        qk = _query_key(query)
        n = 0
        for ins in state["inserts"]:
            if ins["session_id"] != session_id:
                continue
            for r in ins["rows"]:
                if r["metadata"].get("task_query_hash") == qk:
                    n += 1
        return n

    async def _stub_insert(*, session_id, blob_id, source_file_id, source_type,
                            source_filename, source_url, trust_level, rows):
        state["inserts"].append(
            {
                "session_id": session_id,
                "source_type": source_type,
                "trust_level": trust_level,
                "source_url": source_url,
                "rows": rows,
            }
        )
        return [f"id-{i}" for i in range(len(rows))]

    monkeypatch.setattr(ingest_module, "has_cached_news", _stub_has_cached)
    monkeypatch.setattr(ingest_module, "insert_chunks", _stub_insert)
    return state


# ---------------------------------------------------------------------------
# Test 1 — Tavily search results land as chunks with correct metadata
# ---------------------------------------------------------------------------


async def test_tavily_returns_chunked_results(
    stub_embed,  # noqa: ARG001
    stub_db: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_tavily(query, *, max_results=10, days=90, api_key=None, **kwargs):
        return [
            _make_tavily_row(
                url="https://www.reuters.com/business/apple-q4-2024",
                title="Apple posts record Q4",
                raw_content=_long_article("Apple posts record Q4"),
            ),
            _make_tavily_row(
                url="https://www.foo-news.example/apple-q4-recap",
                title="Apple Q4 recap",
                raw_content=_long_article("Apple Q4 recap"),
            ),
        ]

    monkeypatch.setattr(ingest_module, "tavily_search", _fake_tavily)

    result = await fetch_and_ingest_news(
        session_id="00000000-0000-0000-0000-000000000001",
        query="Apple Q4 results",
        api_key="dummy-test-key",
    )
    assert result.cached is False
    assert result.tavily_results == 2
    assert result.articles_chunked == 2
    assert result.chunks_written > 0
    assert result.errors == []

    # Inserts: one per article. Verify metadata shape on a sample row.
    assert len(stub_db["inserts"]) == 2
    first = stub_db["inserts"][0]
    assert first["source_type"] == "news"
    assert first["source_url"].startswith("https://www.reuters.com/")
    sample_meta = first["rows"][0]["metadata"]
    for key in (
        "url",
        "title",
        "source_domain",
        "published_date",
        "task_query",
        "task_query_hash",
    ):
        assert key in sample_meta, f"missing metadata key {key!r}"
    assert sample_meta["source_domain"] == "reuters.com"
    assert sample_meta["task_query"] == "Apple Q4 results"


# ---------------------------------------------------------------------------
# Test 2 — Per-(engagement, query) caching
# ---------------------------------------------------------------------------


async def test_news_priority_caches_per_engagement(
    stub_embed,  # noqa: ARG001
    stub_db: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = {"n": 0}

    async def _fake_tavily(query, *, max_results=10, days=90, api_key=None, **kwargs):
        call_count["n"] += 1
        return [
            _make_tavily_row(
                url=f"https://www.example.test/article-{call_count['n']}",
                title="Apple snippet",
                raw_content=_long_article("Apple Q4 results"),
            )
        ]

    monkeypatch.setattr(ingest_module, "tavily_search", _fake_tavily)

    sid_a = "00000000-0000-0000-0000-0000000000a1"
    sid_b = "00000000-0000-0000-0000-0000000000b2"

    # First call on engagement A — fresh fetch.
    r1 = await fetch_and_ingest_news(session_id=sid_a, query="Apple Q4", api_key="x")
    assert r1.cached is False
    assert call_count["n"] == 1

    # Same engagement, same query — cache hit, no Tavily call.
    r2 = await fetch_and_ingest_news(session_id=sid_a, query="Apple Q4", api_key="x")
    assert r2.cached is True
    assert call_count["n"] == 1

    # Same engagement, different query — fresh fetch.
    r3 = await fetch_and_ingest_news(session_id=sid_a, query="Apple risks", api_key="x")
    assert r3.cached is False
    assert call_count["n"] == 2

    # Different engagement, same original query — fresh fetch (cross-
    # engagement isolation).
    r4 = await fetch_and_ingest_news(session_id=sid_b, query="Apple Q4", api_key="x")
    assert r4.cached is False
    assert call_count["n"] == 3


# ---------------------------------------------------------------------------
# Test 3 — Trust level routing
# ---------------------------------------------------------------------------


async def test_trusted_domain_gets_firm_vetted_trust_level(
    stub_embed,  # noqa: ARG001
    stub_db: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_tavily(query, *, max_results=10, days=90, api_key=None, **kwargs):
        return [
            _make_tavily_row(
                url="https://www.reuters.com/business/apple",
                title="Reuters: Apple Q4",
                raw_content=_long_article("Reuters: Apple Q4"),
            ),
            _make_tavily_row(
                url="https://news.subdomain.bloomberg.com/story",
                title="Bloomberg subdomain",
                raw_content=_long_article("Bloomberg subdomain"),
            ),
            _make_tavily_row(
                url="https://www.random-blog.example/post",
                title="Random blog",
                raw_content=_long_article("Random blog"),
            ),
        ]

    monkeypatch.setattr(ingest_module, "tavily_search", _fake_tavily)
    await fetch_and_ingest_news(
        session_id="00000000-0000-0000-0000-0000000000aa",
        query="trust mapping",
        api_key="x",
    )

    inserts = stub_db["inserts"]
    by_url = {ins["source_url"]: ins for ins in inserts}
    reuters = next(v for k, v in by_url.items() if "reuters.com" in k)
    bloomberg = next(v for k, v in by_url.items() if "bloomberg.com" in k)
    random_blog = next(v for k, v in by_url.items() if "random-blog.example" in k)

    assert reuters["trust_level"] == "firm_vetted"
    # subdomain match: news.subdomain.bloomberg.com → bloomberg.com
    assert bloomberg["trust_level"] == "firm_vetted"
    assert random_blog["trust_level"] == "general"

    # Sanity: TRUSTED_NEWS_DOMAINS exposed at the package level for callers.
    assert "reuters.com" in TRUSTED_NEWS_DOMAINS
    assert "random-blog.example" not in TRUSTED_NEWS_DOMAINS


# ---------------------------------------------------------------------------
# Test 4 — SerpAPI fallback gated by env
# ---------------------------------------------------------------------------


async def test_serpapi_fallback_gated_by_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When TAVILY_API_KEY is set but Tavily fails, ``search_web_structured``
    must return ``[]`` rather than silently falling back to SerpAPI —
    unless ``ARGUS_NEWS_FALLBACK_TO_SERPAPI=true`` is set.
    """
    import core.web_search as ws
    from core.retrievers.news import tavily_client as tc

    # Force Tavily as active provider, simulate a failure.
    monkeypatch.setattr(tc, "TAVILY_API_KEY", "fake-tavily")

    async def _broken_tavily(*args, **kwargs):
        raise TavilyError("simulated Tavily 502")

    monkeypatch.setattr(tc, "tavily_search", _broken_tavily)

    # Provide a SerpAPI key so the fallback PATH is reachable in principle.
    monkeypatch.setattr(ws, "SERPAPI_KEY", "fake-serpapi")

    serpapi_called = {"n": 0}

    async def _fake_serpapi(query, num_results):
        serpapi_called["n"] += 1
        return [{"title": "fallback", "url": "x", "snippet": "x", "position": 1, "date": ""}]

    monkeypatch.setattr(ws, "_search_serpapi", _fake_serpapi)

    # (a) Flag OFF — Tavily is the active provider; on error we get [],
    #     no silent SerpAPI fallback.
    monkeypatch.delenv("ARGUS_NEWS_FALLBACK_TO_SERPAPI", raising=False)
    out = await ws.search_web_structured("Apple", num_results=3)
    assert out == []
    assert serpapi_called["n"] == 0

    # (b) Flag ON — _active_provider() now picks 'serpapi' (because
    #     Tavily key alone doesn't flip provider when fallback is opt-in).
    #     Caller still has to retry; structured returns Tavily-result on
    #     happy path, SerpAPI when the operator explicitly opts in.
    monkeypatch.setenv("ARGUS_NEWS_FALLBACK_TO_SERPAPI", "true")
    # With Tavily key set AND fallback enabled, Tavily is still tried
    # first (returns []) — the active provider with a key is preferred.
    # We assert the flag is read correctly via the helper.
    assert ws._serpapi_fallback_enabled() is True
    # Force Tavily key off so we land in serpapi branch.
    monkeypatch.setattr(tc, "TAVILY_API_KEY", "")
    monkeypatch.setattr(ws, "BRAVE_API_KEY", "")
    out2 = await ws.search_web_structured("Apple", num_results=3)
    assert serpapi_called["n"] == 1
    assert out2 and out2[0]["title"] == "fallback"


# ---------------------------------------------------------------------------
# Bonus — chunker drops empty / tiny inputs
# ---------------------------------------------------------------------------


def test_chunker_handles_empty_and_tiny() -> None:
    assert chunk_news_article("") == []
    assert chunk_news_article("   ") == []
    # All paragraphs too short → boilerplate filter drops everything.
    assert chunk_news_article("hi.\n\nthere.") == []
