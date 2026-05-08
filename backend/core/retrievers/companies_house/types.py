"""Frozen dataclasses + exceptions for the Companies House client."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CHCompanyInfo:
    """Companies House company resolution result.

    Attributes
    ----------
    company_number:
        Eight-character zero-padded company number (e.g. ``"00445790"``
        for Tesco). Companies House uses this as the primary key for
        every other endpoint. The padding format matters — bare integer
        forms like ``"445790"`` are rejected by the document API.
    company_name:
        Registered name as Companies House reports it.
    company_status:
        ``"active"`` for going-concern firms; other values include
        ``"dissolved"``, ``"liquidation"``, ``"administration"``.
        Surface to ingestion callers so they can decide whether to
        proceed with a dissolved entity.
    """

    company_number: str
    company_name: str
    company_status: str = "active"


@dataclass(frozen=True)
class CHFiling:
    """One filing reference from /company/{number}/filing-history.

    Companies House groups filings by ``category`` (accounts,
    confirmation-statement, capital, etc.) and gives each a
    ``transaction_id`` plus a ``description`` like
    ``"accounts-with-accounts-type-full"``.

    Attributes
    ----------
    transaction_id:
        CH's identifier for this filing (e.g. ``"MzM2NTEx..."``).
        Idempotency key for ingestion — re-running with the same
        transaction_id is a no-op.
    category:
        High-level filing category, e.g. ``"accounts"`` or
        ``"confirmation-statement"``. Phase 1 ingests ``"accounts"`` only.
    description:
        Filing sub-type, e.g. ``"accounts-with-accounts-type-full"``,
        ``"accounts-with-accounts-type-group"``,
        ``"accounts-with-accounts-type-micro-entity"``.
    filing_date:
        ISO-8601 ``date`` field — when the filing was filed.
    period_end:
        Period the accounts cover (``made_up_date``). Often differs
        from ``filing_date`` by 6-9 months.
    document_id:
        Tail of the document-API URL — ``/document/{document_id}``.
        Required to fetch the PDF.
    """

    transaction_id: str
    category: str
    description: str
    filing_date: str
    period_end: str
    document_id: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CompaniesHouseError(Exception):
    """Base exception for the Companies House retriever."""


class CompanyNotFoundError(CompaniesHouseError):
    """Raised when ``resolve_company`` can't match the input string."""
