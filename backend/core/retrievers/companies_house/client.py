"""Polite, rate-limited Companies House client.

Companies House publishes a 600-requests-per-5-minutes limit (their
docs: https://developer.company-information.service.gov.uk/manage-applications).
We model that as a 2 req/sec token bucket with a 60-token capacity, so
the first 60 requests fire freely and subsequent traffic meters out.
Same fail-closed semantics as the EDGAR client.

Auth: HTTP Basic — API key as username, empty password. The key is read
from ``COMPANIES_HOUSE_API_KEY``.

Public methods on :class:`CompaniesHouseClient`:

  - :meth:`resolve_company` — name-or-number string → :class:`CHCompanyInfo`
  - :meth:`get_filings` — company number → list of :class:`CHFiling`
  - :meth:`fetch_document` — :class:`CHFiling` → PDF bytes
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time
from typing import Any

import httpx

from core.retrievers.companies_house.types import (
    CHCompanyInfo,
    CHFiling,
    CompaniesHouseError,
    CompanyNotFoundError,
)

logger = logging.getLogger(__name__)

API_BASE = "https://api.company-information.service.gov.uk"
DOCUMENT_API_BASE = "https://document-api.company-information.service.gov.uk"

_DEFAULT_TIMEOUT_SECONDS: float = 30.0
_DEFAULT_RATE_PER_SECOND: float = 2.0  # 600 / 300s
_DEFAULT_BUCKET_CAPACITY: int = 60
_DEFAULT_MAX_WAIT_SECONDS: float = 5.0
_NUMBER_RE = re.compile(r"^[0-9A-Z]{6,8}$")


def _clean_key(raw: str | None) -> str:
    if not raw:
        return ""
    return raw.split("#", 1)[0].strip()


def _pad_company_number(num: str) -> str:
    """CH expects zero-padded 8-char numbers; user input often drops zeroes."""
    s = (num or "").strip().upper()
    if s.isdigit():
        return s.zfill(8)
    return s


# ---------------------------------------------------------------------------
# Token bucket — same shape as EDGAR's
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Async token bucket. Fail-closed via ``max_wait``."""

    def __init__(
        self,
        rate: float = _DEFAULT_RATE_PER_SECOND,
        capacity: int = _DEFAULT_BUCKET_CAPACITY,
        max_wait: float = _DEFAULT_MAX_WAIT_SECONDS,
    ) -> None:
        self._rate = float(rate)
        self._capacity = float(capacity)
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._max_wait = float(max_wait)
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        sleep_for = 0.0
        async with self._lock:
            now = time.monotonic()
            elapsed = max(0.0, now - self._last_refill)
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            deficit = 1.0 - self._tokens
            sleep_for = deficit / self._rate
            if sleep_for > self._max_wait:
                raise CompaniesHouseError(
                    f"rate limit: would wait {sleep_for:.1f}s for a token "
                    f"(max_wait={self._max_wait:.1f}s)"
                )
            self._tokens = 0.0  # spending the token we're about to acquire
        await asyncio.sleep(sleep_for)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class CompaniesHouseClient:
    """HTTP client with rate limiting + Basic auth wired to CH conventions.

    Usage::

        async with CompaniesHouseClient() as ch:
            info = await ch.resolve_company("Tesco")
            filings = await ch.get_filings(info.company_number)
            pdf_bytes = await ch.fetch_document(filings[0])
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        key = _clean_key(api_key) if api_key is not None else _clean_key(os.getenv("COMPANIES_HOUSE_API_KEY"))
        self._api_key = key
        # Basic auth: key as username, empty password.
        encoded = base64.b64encode(f"{key}:".encode("utf-8")).decode("ascii") if key else ""
        headers = {
            "Authorization": f"Basic {encoded}" if encoded else "",
            "Accept": "application/json",
        }
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={k: v for k, v in headers.items() if v},
            transport=transport,
            follow_redirects=True,
        )
        self._bucket = _TokenBucket()

    async def __aenter__(self) -> CompaniesHouseClient:
        if not self._api_key:
            raise CompaniesHouseError(
                "COMPANIES_HOUSE_API_KEY is not set — cannot make CH requests"
            )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # -----------------------------------------------------------------
    # Resolve
    # -----------------------------------------------------------------

    async def resolve_company(self, name_or_number: str) -> CHCompanyInfo:
        """Resolve a name or number → :class:`CHCompanyInfo`.

        Numbers (8-char zero-padded, e.g. ``"00445790"``) hit
        ``/company/{number}`` directly. Anything else goes through
        ``/search/companies`` and we take the top-ranked active hit.
        """
        s = (name_or_number or "").strip()
        if not s:
            raise CompanyNotFoundError("empty input")

        padded = _pad_company_number(s)
        if _NUMBER_RE.match(padded):
            return await self._fetch_company_profile(padded)

        # Treat as a name search.
        await self._bucket.acquire()
        resp = await self._client.get(f"{API_BASE}/search/companies", params={"q": s, "items_per_page": 10})
        if resp.status_code == 404:
            raise CompanyNotFoundError(s)
        resp.raise_for_status()
        items = resp.json().get("items") or []
        # Prefer active companies; otherwise take the first item.
        active = [it for it in items if str(it.get("company_status") or "").lower() == "active"]
        pick = (active or items)[0] if items else None
        if not pick:
            raise CompanyNotFoundError(s)
        number = _pad_company_number(str(pick.get("company_number") or ""))
        return await self._fetch_company_profile(number)

    async def _fetch_company_profile(self, number: str) -> CHCompanyInfo:
        await self._bucket.acquire()
        resp = await self._client.get(f"{API_BASE}/company/{number}")
        if resp.status_code == 404:
            raise CompanyNotFoundError(f"company {number} not found")
        resp.raise_for_status()
        body = resp.json()
        return CHCompanyInfo(
            company_number=number,
            company_name=str(body.get("company_name") or ""),
            company_status=str(body.get("company_status") or "active"),
        )

    # -----------------------------------------------------------------
    # Filings
    # -----------------------------------------------------------------

    async def get_filings(
        self,
        company_number: str,
        *,
        categories: list[str] | None = None,
        items_per_page: int = 35,
    ) -> list[CHFiling]:
        """Return filings for ``company_number`` filtered by ``categories``.

        Default ``categories`` is ``["accounts"]``: Phase 1's only
        target. Pass an explicit list to widen (e.g.
        ``["accounts", "confirmation-statement"]``).
        """
        number = _pad_company_number(company_number)
        cats = categories or ["accounts"]
        params: dict[str, Any] = {"items_per_page": int(items_per_page)}
        if cats:
            params["category"] = ",".join(cats)
        await self._bucket.acquire()
        resp = await self._client.get(
            f"{API_BASE}/company/{number}/filing-history",
            params=params,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        rows = resp.json().get("items") or []
        out: list[CHFiling] = []
        for r in rows:
            tx = str(r.get("transaction_id") or "").strip()
            if not tx:
                continue
            links = r.get("links") or {}
            doc_link = str(links.get("document_metadata") or "").strip()
            # document_metadata is a full URL like
            # https://document-api.company-information.service.gov.uk/document/{id}
            doc_id = ""
            if doc_link:
                doc_id = doc_link.rstrip("/").rsplit("/", 1)[-1]
            out.append(
                CHFiling(
                    transaction_id=tx,
                    category=str(r.get("category") or ""),
                    description=str(r.get("description") or ""),
                    filing_date=str(r.get("date") or ""),
                    period_end=str((r.get("description_values") or {}).get("made_up_date") or ""),
                    document_id=doc_id,
                )
            )
        return out

    # -----------------------------------------------------------------
    # Document fetch
    # -----------------------------------------------------------------

    async def fetch_document(self, filing: CHFiling) -> bytes:
        """Download a filing's primary document as raw bytes (almost always PDF).

        Two-step request: first hit document-api for the metadata (which
        returns a redirect-like ``content_url`` pointing at the actual
        PDF), then GET that URL with ``Accept: application/pdf``. CH's
        own httpx redirects don't always carry through, so we do it
        explicitly.
        """
        if not filing.document_id:
            raise CompaniesHouseError(
                f"filing {filing.transaction_id} has no document_id"
            )
        # Direct fetch of the binary content. The document API responds to
        # GET /document/{id}/content with a 302 to a temporary AWS URL.
        # httpx's follow_redirects handles that for us.
        await self._bucket.acquire()
        url = f"{DOCUMENT_API_BASE}/document/{filing.document_id}/content"
        resp = await self._client.get(url, headers={"Accept": "application/pdf"})
        resp.raise_for_status()
        return resp.content
