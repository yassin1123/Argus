"""SEC EDGAR retriever (Phase 1 / Week 3 / Day 1).

Public surface:

    from core.retrievers.edgar import EdgarClient, CompanyInfo, Filing

See ``client.py`` for the rate-limiting / User-Agent / caching contract.
"""

from core.retrievers.edgar.chunker import FilingChunk, chunk_filing
from core.retrievers.edgar.client import EdgarClient
from core.retrievers.edgar.ingest import IngestResult, ingest_filings
from core.retrievers.edgar.parser import FilingSection, parse_filing_sections
from core.retrievers.edgar.types import (
    CompanyInfo,
    EdgarError,
    Filing,
    FilingDocument,
    RateLimitedError,
    TickerNotFoundError,
)

__all__ = [
    "EdgarClient",
    "CompanyInfo",
    "Filing",
    "FilingDocument",
    "FilingSection",
    "FilingChunk",
    "IngestResult",
    "EdgarError",
    "TickerNotFoundError",
    "RateLimitedError",
    "parse_filing_sections",
    "chunk_filing",
    "ingest_filings",
]
