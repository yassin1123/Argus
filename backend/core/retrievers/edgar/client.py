"""Polite, rate-limited SEC EDGAR client.

Phase 1 / Week 3 / Day 1. Three public methods on :class:`EdgarClient`:

- :meth:`resolve_ticker` — ticker → ``CompanyInfo`` (cik/name/ticker)
- :meth:`list_filings` — CIK → most-recent-first ``list[Filing]``
- :meth:`fetch_document` — ``Filing`` → raw ``FilingDocument``

WHAT SEC.GOV REQUIRES
=====================
Every request to ``data.sec.gov`` and ``www.sec.gov`` MUST carry a
``User-Agent`` header that names a real human + email — anonymous
requests are blocked. The header is read from the ``ARGUS_SEC_USER_AGENT``
env var; the default ``"Argus Research argus-ops@example.com"`` is fine
for development but should be overridden in production. SEC publishes
their fair-use rules at https://www.sec.gov/os/accessing-edgar-data.

RATE LIMIT
==========
SEC's published cap is 10 requests/second across the whole service.
The :class:`_TokenBucket` below enforces this locally with fail-closed
semantics: if a request would have to wait more than ``max_wait`` seconds
for a token, we raise :class:`RateLimitedError` instead of queueing
indefinitely. The acceptance threshold is 5 seconds — callers that need
longer should back off and retry, not block.

WHY NOT JUST USE A SEMAPHORE
============================
A semaphore caps *concurrency* (n requests in flight at once) but
doesn't cap *rate* (n requests per second). For SEC's rule, the bucket
is the right primitive — it lets the first 10 requests fire instantly,
then meters subsequent requests at exactly the rate the bucket refills.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from core.retrievers.edgar.types import (
    CompanyInfo,
    EdgarError,
    Filing,
    FilingDocument,
    RateLimitedError,
    TickerNotFoundError,
)

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Argus Research argus-ops@example.com"
DATA_BASE = "https://data.sec.gov"
WWW_BASE = "https://www.sec.gov"
TICKERS_PATH = "/files/company_tickers.json"
SUBMISSIONS_PATH_TEMPLATE = "/submissions/CIK{cik:010d}.json"
ARCHIVES_PATH_TEMPLATE = "/Archives/edgar/data/{cik_int}/{accession_no_dashes}/{primary}"

_TICKERS_CACHE_TTL_SECONDS: float = 24 * 3600.0
_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_DEFAULT_RATE_PER_SECOND: int = 10
_DEFAULT_MAX_WAIT_SECONDS: float = 5.0


# ---------------------------------------------------------------------------
# Rate limiter (token bucket)
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Async token bucket. ``capacity`` tokens, refills at ``rate`` per second.

    ``max_wait`` is fail-closed: if :meth:`acquire` would have to sleep
    longer than that to get a token, it raises :class:`RateLimitedError`.
    The lock serialises bookkeeping but still lets callers see contention
    via the elapsed-sleep duration; we do NOT hold the lock during sleep.
    """

    def __init__(
        self,
        rate: float = float(_DEFAULT_RATE_PER_SECOND),
        capacity: int | None = None,
        max_wait: float = _DEFAULT_MAX_WAIT_SECONDS,
    ) -> None:
        self._rate = float(rate)
        self._capacity = float(capacity if capacity is not None else rate)
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._max_wait = float(max_wait)
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        sleep_for = 0.0
        async with self._lock:
            now = time.monotonic()
            # ``elapsed`` should be non-negative because we always set
            # ``_last_refill = now`` at the bottom of this critical section.
            # Clamp defensively in case clock jitter ever produces a small
            # negative — going negative on tokens is fine (it queues
            # waiters) but going more negative than -1 because of clock
            # drift would falsely trigger RateLimitedError.
            elapsed = max(0.0, now - self._last_refill)
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            # Bucket empty. The Nth waiter sees ``_tokens = -(N-1)`` and
            # therefore waits ``N / _rate`` seconds. Each subsequent
            # waiter naturally accrues a longer sleep — exactly the
            # spacing the SEC rate cap requires.
            sleep_for = (1.0 - self._tokens) / self._rate
            if sleep_for > self._max_wait:
                raise RateLimitedError(
                    f"local rate limiter would block {sleep_for:.2f}s "
                    f"(max_wait={self._max_wait:.2f}s); back off and retry"
                )
            self._tokens -= 1.0
            # Do NOT pre-shift _last_refill into the future — that would
            # make the *next* acquire compute a negative elapsed and
            # over-decrement, compounding waits across concurrent callers.
        await asyncio.sleep(sleep_for)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class EdgarClient:
    """Polite SEC EDGAR client. Use as an async context manager so the
    underlying ``httpx.AsyncClient`` is closed cleanly.
    """

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        data_base: str = DATA_BASE,
        www_base: str = WWW_BASE,
        rate_per_second: int = _DEFAULT_RATE_PER_SECOND,
        max_wait_seconds: float = _DEFAULT_MAX_WAIT_SECONDS,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        ua = user_agent or os.getenv("ARGUS_SEC_USER_AGENT") or DEFAULT_USER_AGENT
        if ua == DEFAULT_USER_AGENT:
            logger.warning(
                "EdgarClient using default User-Agent %r — set ARGUS_SEC_USER_AGENT "
                "for production. SEC blocks generic / missing UAs.",
                ua,
            )
        self._headers = {
            "User-Agent": ua,
            # gzip dramatically reduces 10-K transfer time; httpx decodes
            # transparently and reports length_bytes after decoding.
            "Accept-Encoding": "gzip, deflate",
            # SEC servers have been observed to return 404 when the Host
            # is missing (httpx sets it automatically). Documented for
            # future debugging only.
        }
        self._user_agent = ua
        self._data_base = data_base.rstrip("/")
        self._www_base = www_base.rstrip("/")
        kwargs: dict[str, Any] = {
            "headers": self._headers,
            "timeout": timeout_seconds,
            "follow_redirects": True,
        }
        if transport is not None:
            kwargs["transport"] = transport
        self._client = httpx.AsyncClient(**kwargs)
        self._bucket = _TokenBucket(rate=rate_per_second, max_wait=max_wait_seconds)
        self._tickers_cache: dict[str, CompanyInfo] | None = None
        self._tickers_cached_at: float = 0.0

    # ------------------------------------------------------------------ ctx
    async def __aenter__(self) -> "EdgarClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ----------------------------------------------------------- resolve()
    async def _load_tickers_table(self) -> dict[str, CompanyInfo]:
        now = time.monotonic()
        if self._tickers_cache is not None and (now - self._tickers_cached_at) < _TICKERS_CACHE_TTL_SECONDS:
            return self._tickers_cache
        await self._bucket.acquire()
        url = f"{self._www_base}{TICKERS_PATH}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception as e:  # noqa: BLE001
            raise EdgarError(f"company_tickers.json is not valid JSON: {e}") from e

        # Upstream shape: {"0": {"cik_str": int, "ticker": str, "title": str}, ...}
        table: dict[str, CompanyInfo] = {}
        if not isinstance(payload, dict):
            raise EdgarError(
                f"company_tickers.json: expected dict, got {type(payload).__name__}"
            )
        for row in payload.values():
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip().upper()
            cik_int = row.get("cik_str")
            name = str(row.get("title") or "").strip()
            if not ticker or cik_int is None:
                continue
            try:
                cik_padded = f"{int(cik_int):010d}"
            except (TypeError, ValueError):
                continue
            table[ticker] = CompanyInfo(cik=cik_padded, name=name, ticker=ticker)
        self._tickers_cache = table
        self._tickers_cached_at = now
        logger.info("EdgarClient: cached %d ticker rows", len(table))
        return table

    async def resolve_ticker(self, ticker: str) -> CompanyInfo:
        """Look up a ticker symbol in SEC's company_tickers.json table.

        The table is cached in-memory for 24 hours per process — it
        changes rarely and SEC's policy explicitly encourages caching.
        Raises :class:`TickerNotFoundError` if the ticker isn't present.
        """
        sym = (ticker or "").strip().upper()
        if not sym:
            raise TickerNotFoundError("ticker is empty")
        table = await self._load_tickers_table()
        info = table.get(sym)
        if info is None:
            raise TickerNotFoundError(f"ticker {sym!r} not in SEC company_tickers.json")
        return info

    # -------------------------------------------------------- list_filings()
    @staticmethod
    def _build_primary_doc_url(
        www_base: str, cik: str, accession_number: str, primary: str
    ) -> str:
        cik_int = int(cik)
        accession_no_dashes = accession_number.replace("-", "")
        path = ARCHIVES_PATH_TEMPLATE.format(
            cik_int=cik_int,
            accession_no_dashes=accession_no_dashes,
            primary=primary,
        )
        return f"{www_base}{path}"

    async def list_filings(
        self,
        cik: str,
        forms: list[str] | None = None,
        limit: int = 50,
    ) -> list[Filing]:
        """List filings for a CIK, most-recent-first, optionally filtered
        to specific forms (e.g. ``["10-K", "10-Q"]``).

        Pulls from ``data.sec.gov/submissions/CIK{cik:010d}.json``.
        """
        try:
            cik_int = int(cik)
        except (TypeError, ValueError) as e:
            raise EdgarError(f"cik must be numeric, got {cik!r}") from e
        await self._bucket.acquire()
        url = f"{self._data_base}{SUBMISSIONS_PATH_TEMPLATE.format(cik=cik_int)}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        payload = resp.json()

        # Upstream shape:
        #   {"cik": "320193",
        #    "filings": {"recent": {"accessionNumber": [...], "form": [...],
        #                            "filingDate": [...], "reportDate": [...],
        #                            "primaryDocument": [...], ...}}}
        filings_block = (payload or {}).get("filings") or {}
        recent = filings_block.get("recent") or {}
        accs = list(recent.get("accessionNumber") or [])
        forms_arr = list(recent.get("form") or [])
        filing_dates = list(recent.get("filingDate") or [])
        report_dates = list(recent.get("reportDate") or [])
        primary_docs = list(recent.get("primaryDocument") or [])

        n = min(len(accs), len(forms_arr), len(filing_dates), len(primary_docs))
        if n == 0:
            return []

        cik_padded = f"{cik_int:010d}"
        forms_filter = {f.strip().upper() for f in forms} if forms else None

        out: list[Filing] = []
        for i in range(n):
            form_i = str(forms_arr[i]).strip()
            if forms_filter is not None and form_i.upper() not in forms_filter:
                continue
            acc = str(accs[i]).strip()
            primary = str(primary_docs[i]).strip()
            if not acc or not primary:
                continue
            url_i = self._build_primary_doc_url(self._www_base, cik_padded, acc, primary)
            out.append(
                Filing(
                    accession_number=acc,
                    form=form_i,
                    filing_date=str(filing_dates[i]).strip(),
                    primary_document=primary,
                    primary_doc_url=url_i,
                    report_date=(
                        str(report_dates[i]).strip()
                        if i < len(report_dates) and report_dates[i]
                        else ""
                    ),
                )
            )
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------- fetch_document()
    async def fetch_document(self, filing: Filing) -> FilingDocument:
        """Download the primary document of ``filing`` verbatim.

        No HTML parsing — Day 2 chunks. Returns the raw text + the
        Content-Type header + length so callers can see at a glance
        what they're dealing with.
        """
        if not filing.primary_doc_url:
            raise EdgarError(f"filing {filing.accession_number} has no primary_doc_url")
        await self._bucket.acquire()
        resp = await self._client.get(filing.primary_doc_url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        text = resp.text
        return FilingDocument(
            filing=filing,
            raw_html=text,
            content_type=content_type,
            length_bytes=len(resp.content),
        )
