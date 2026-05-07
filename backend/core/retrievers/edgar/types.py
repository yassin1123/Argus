"""Frozen dataclasses + exception types for the SEC EDGAR client.

Phase 1 / Week 3 / Day 1. Plain dataclasses (not Pydantic) match the
existing style in core/retrievers and keep this module's import cost
minimal — the EDGAR retriever can be imported by tools/edgar_inspect.py
without dragging Pydantic / FastAPI in.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompanyInfo:
    """One row of SEC's ticker → CIK lookup table.

    Attributes
    ----------
    cik:
        Zero-padded 10-digit CIK string (e.g. ``"0000320193"``). Always
        ten characters; we pad in :func:`EdgarClient.resolve_ticker`
        regardless of what the upstream JSON returns so callers don't
        have to remember.
    name:
        Company name as SEC reports it (e.g. ``"Apple Inc."``).
    ticker:
        Uppercase ticker symbol (e.g. ``"AAPL"``).
    """

    cik: str
    name: str
    ticker: str


@dataclass(frozen=True)
class Filing:
    """One filing reference from the SEC submissions endpoint.

    The fields parallel the upstream
    ``data.sec.gov/submissions/CIK{cik:010d}.json`` shape — see
    :func:`EdgarClient.list_filings` for the parsing.

    Attributes
    ----------
    accession_number:
        SEC's filing accession in the dashed form, e.g.
        ``"0000320193-24-000123"``.
    form:
        Form type, e.g. ``"10-K"``, ``"10-Q"``, ``"8-K"``,
        ``"DEF 14A"``, ``"S-1"``.
    filing_date:
        ISO-8601 date the filing was submitted, e.g. ``"2024-09-28"``.
    primary_document:
        Filename of the primary document inside the filing, e.g.
        ``"aapl-20240928.htm"``.
    primary_doc_url:
        Fully-qualified URL to the primary document on
        ``www.sec.gov/Archives/...``. Computed from ``cik`` +
        ``accession_number`` + ``primary_document``.
    report_date:
        ISO-8601 date of the filing's reporting period (often the
        fiscal-year end for 10-K, quarter end for 10-Q). May be empty
        when SEC doesn't populate it.
    """

    accession_number: str
    form: str
    filing_date: str
    primary_document: str
    primary_doc_url: str
    report_date: str


@dataclass(frozen=True)
class FilingDocument:
    """The raw download of a filing's primary document.

    Day 1 stops here — no HTML parsing, no chunking. The HTML stays
    in ``raw_html`` for Day 2's chunker to consume.

    Attributes
    ----------
    filing:
        The :class:`Filing` reference that produced this document.
    raw_html:
        The document body verbatim. Almost always HTML for 10-K/10-Q,
        but a few older filings serve plain text — caller decides what
        to do with it.
    content_type:
        ``Content-Type`` header reported by sec.gov.
    length_bytes:
        Byte length of the response body (after gzip/deflate decoding,
        as httpx returns it).
    """

    filing: Filing
    raw_html: str
    content_type: str
    length_bytes: int


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class EdgarError(Exception):
    """Base class for any error raised by ``core.retrievers.edgar``."""


class TickerNotFoundError(EdgarError):
    """Raised when ``resolve_ticker`` can't find the symbol in SEC's table."""


class RateLimitedError(EdgarError):
    """Raised when the local rate limiter would block longer than its
    configured ``max_wait`` budget. Fail-closed semantics — the caller is
    expected to back off rather than queue indefinitely.
    """
