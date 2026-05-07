"""SEC EDGAR client tests (Week 3 / Day 1).

Five fast unit tests run with ``httpx.MockTransport`` (no network). One
real-API canary is gated behind ``ARGUS_RUN_EDGAR_INTEGRATION=1`` and
skipped by default — running it on every CI cycle would be both wasteful
and rude to sec.gov.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.retrievers.edgar import (
    CompanyInfo,
    EdgarClient,
    Filing,
    RateLimitedError,
    TickerNotFoundError,
)
from core.retrievers.edgar.client import _TokenBucket

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "edgar"


def _load_fixture(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _make_handler(*, expect_user_agent: bool = True):
    """Build a MockTransport handler that serves the fixture endpoints.

    Records every request's User-Agent on the closure so individual tests
    can assert it.
    """
    seen_user_agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_user_agents.append(request.headers.get("user-agent", ""))
        url = str(request.url)
        if url.endswith("/files/company_tickers.json"):
            return httpx.Response(200, json=_load_fixture("company_tickers.json"))
        if "/submissions/CIK" in url and url.endswith(".json"):
            return httpx.Response(200, json=_load_fixture("apple_submissions.json"))
        if "/Archives/edgar/data/" in url:
            return httpx.Response(
                200,
                content=b"<html><body><p>fake 10-K body</p></body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        return httpx.Response(404, text=f"unmocked path: {url}")

    return handler, seen_user_agents


# ---------------------------------------------------------------------------
# resolve_ticker
# ---------------------------------------------------------------------------


async def test_resolve_ticker_apple() -> None:
    handler, _ = _make_handler()
    async with EdgarClient(transport=httpx.MockTransport(handler)) as client:
        info = await client.resolve_ticker("AAPL")
    assert isinstance(info, CompanyInfo)
    assert info.cik == "0000320193"
    assert info.name == "Apple Inc."
    assert info.ticker == "AAPL"


async def test_resolve_ticker_invalid() -> None:
    handler, _ = _make_handler()
    async with EdgarClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TickerNotFoundError):
            await client.resolve_ticker("NOPE")


async def test_resolve_ticker_lowercase_input_normalises() -> None:
    """Operator types ``aapl`` not ``AAPL``; resolve_ticker should not care."""
    handler, _ = _make_handler()
    async with EdgarClient(transport=httpx.MockTransport(handler)) as client:
        info = await client.resolve_ticker("aapl")
    assert info.ticker == "AAPL"


# ---------------------------------------------------------------------------
# list_filings
# ---------------------------------------------------------------------------


async def test_list_filings_filters_by_form() -> None:
    handler, _ = _make_handler()
    async with EdgarClient(transport=httpx.MockTransport(handler)) as client:
        only_10k = await client.list_filings("0000320193", forms=["10-K"])
    assert len(only_10k) == 2  # fixture has two 10-K rows
    assert all(f.form == "10-K" for f in only_10k)
    # Most-recent-first ordering preserved.
    assert only_10k[0].filing_date == "2024-11-01"
    assert only_10k[1].filing_date == "2023-11-03"


async def test_list_filings_no_filter_returns_all() -> None:
    handler, _ = _make_handler()
    async with EdgarClient(transport=httpx.MockTransport(handler)) as client:
        rows = await client.list_filings("0000320193")
    # Fixture has 5 filings.
    assert len(rows) == 5
    assert {f.form for f in rows} == {"10-K", "10-Q"}


async def test_list_filings_primary_doc_url_well_formed() -> None:
    handler, _ = _make_handler()
    async with EdgarClient(transport=httpx.MockTransport(handler)) as client:
        rows = await client.list_filings("0000320193", forms=["10-K"], limit=1)
    assert rows
    f = rows[0]
    # cik_int=320193, accession=0000320193-24-000123 -> 000032019324000123
    expected = (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019324000123/aapl-20240928.htm"
    )
    assert f.primary_doc_url == expected


# ---------------------------------------------------------------------------
# fetch_document — round-trips a synthetic body
# ---------------------------------------------------------------------------


async def test_fetch_document_returns_raw_body() -> None:
    handler, _ = _make_handler()
    async with EdgarClient(transport=httpx.MockTransport(handler)) as client:
        rows = await client.list_filings("0000320193", forms=["10-K"], limit=1)
        doc = await client.fetch_document(rows[0])
    assert "fake 10-K body" in doc.raw_html
    assert doc.content_type == "text/html"
    assert doc.length_bytes == len(b"<html><body><p>fake 10-K body</p></body></html>")
    assert doc.filing.accession_number == rows[0].accession_number


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


async def test_rate_limit_enforced() -> None:
    """Fire 15 requests in a tight loop. With a 10/s bucket, the 11th
    request onwards must wait ~100ms apiece. The test asserts at least
    one acquire took >=100ms — a softer bar than "exactly five did" so
    timing wobble doesn't make the test flaky.
    """
    handler, _ = _make_handler()
    async with EdgarClient(
        transport=httpx.MockTransport(handler),
        # 5s default max_wait gives the 10th-15th tokens room to refill
        # (5 extra tokens at 10/s = 0.5s wait — well under the budget).
        max_wait_seconds=5.0,
    ) as client:
        # Hit a fast path (cached after the first resolve) so we measure
        # the rate limiter, not network latency.
        await client.resolve_ticker("AAPL")
        delays_ms: list[float] = []
        for _ in range(15):
            t0 = time.monotonic()
            await client._bucket.acquire()  # type: ignore[attr-defined]
            delays_ms.append((time.monotonic() - t0) * 1000.0)
    delayed = [d for d in delays_ms if d >= 100.0]
    assert delayed, (
        f"expected at least one acquire to be delayed >=100ms; "
        f"all delays (ms) = {[round(d, 1) for d in delays_ms]}"
    )


async def test_rate_limit_fail_closed_short_budget() -> None:
    """If max_wait is tiny, the bucket should refuse rather than queue."""
    bucket = _TokenBucket(rate=10.0, capacity=1, max_wait=0.001)
    await bucket.acquire()  # consume the one token
    with pytest.raises(RateLimitedError):
        await bucket.acquire()  # would need ~100ms but max_wait is 1ms


async def test_rate_limit_does_not_deadlock_under_load() -> None:
    """50 concurrent acquires with default 10/s + 5s max_wait: should
    finish in < 6 seconds and not raise (50 tokens / 10 per second = 5s).
    """
    bucket = _TokenBucket(rate=10.0, max_wait=10.0)
    t0 = time.monotonic()
    await asyncio.gather(*(bucket.acquire() for _ in range(50)))
    elapsed = time.monotonic() - t0
    assert elapsed < 6.0, f"50 acquires took {elapsed:.2f}s; expected < 6s"


# ---------------------------------------------------------------------------
# User-Agent header
# ---------------------------------------------------------------------------


async def test_user_agent_header_set() -> None:
    handler, seen_user_agents = _make_handler()
    custom_ua = "Argus Research test-suite@example.com"
    async with EdgarClient(
        user_agent=custom_ua,
        transport=httpx.MockTransport(handler),
    ) as client:
        await client.resolve_ticker("AAPL")
        rows = await client.list_filings("0000320193", forms=["10-K"], limit=1)
        await client.fetch_document(rows[0])
    assert seen_user_agents
    assert all(ua == custom_ua for ua in seen_user_agents), (
        f"every outbound request must carry the configured User-Agent; "
        f"got {seen_user_agents}"
    )


# ---------------------------------------------------------------------------
# Integration canary — only runs with ARGUS_RUN_EDGAR_INTEGRATION=1
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("ARGUS_RUN_EDGAR_INTEGRATION") != "1",
    reason="set ARGUS_RUN_EDGAR_INTEGRATION=1 to run real-API canary against sec.gov",
)
async def test_apple_10k_real() -> None:
    """Real call to sec.gov. Bounded politely: one ticker resolve + one
    submissions fetch + (optional) one document fetch. Do NOT pull more
    than 3 filings from this test — sec.gov is a public good.
    """
    async with EdgarClient() as client:
        info = await client.resolve_ticker("AAPL")
        assert info.cik == "0000320193"
        assert info.ticker == "AAPL"
        filings = await client.list_filings(info.cik, forms=["10-K"], limit=3)
    assert filings, "Apple should have at least one 10-K on file"
    most_recent = filings[0]
    assert most_recent.form == "10-K"
    assert most_recent.primary_doc_url.startswith("https://www.sec.gov/Archives/edgar/data/")
    assert most_recent.primary_doc_url.endswith(".htm") or most_recent.primary_doc_url.endswith(".html")
    assert len(filings) <= 3
