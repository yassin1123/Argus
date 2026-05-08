"""UK Companies House retriever (Phase 1 / Week 4 / Day 4).

Sister module to ``core.retrievers.edgar``. Same end-to-end shape:

  client.resolve_company  -> CompanyInfo
  client.get_filings      -> list[Filing]
  client.fetch_document   -> PDF bytes
  parser.parse_pdf        -> list[FilingSection]  (reuses EDGAR's shape)
  chunker.chunk_filing    -> list[FilingChunk]    (reused from EDGAR)
  ingest.ingest_company   -> writes to chunks table with
                             source_type='ch_filing', trust_level='firm_vetted'

Trust level: ``firm_vetted`` because Companies House data is statutory.
Idempotency: keyed on (company_number, transaction_id) — CH's own
filing identifier.

Hard rules (Day 4):
  - PDFs treated as raw text. No iXBRL parsing today (Phase 3).
  - Officers / charges are document metadata, not text chunks.
  - Separate retriever, separate code (no Companies House logic in the
    EDGAR module).
"""

from core.retrievers.companies_house.client import CompaniesHouseClient
from core.retrievers.companies_house.ingest import (
    IngestResult,
    ingest_company,
)
from core.retrievers.companies_house.parser import parse_pdf
from core.retrievers.companies_house.types import (
    CHCompanyInfo,
    CHFiling,
    CompaniesHouseError,
    CompanyNotFoundError,
)

__all__ = [
    "CHCompanyInfo",
    "CHFiling",
    "CompaniesHouseClient",
    "CompaniesHouseError",
    "CompanyNotFoundError",
    "IngestResult",
    "ingest_company",
    "parse_pdf",
]
