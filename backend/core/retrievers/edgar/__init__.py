"""SEC EDGAR retriever (Phase 1 / Week 3 / Day 1).

Public surface:

    from core.retrievers.edgar import EdgarClient, CompanyInfo, Filing

See ``client.py`` for the rate-limiting / User-Agent / caching contract.
"""

from core.retrievers.edgar.client import EdgarClient
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
    "EdgarError",
    "TickerNotFoundError",
    "RateLimitedError",
]
