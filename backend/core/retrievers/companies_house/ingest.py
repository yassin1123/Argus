"""End-to-end Companies House ingestion.

Mirror of :mod:`core.retrievers.edgar.ingest`. One async entry-point —
:func:`ingest_company` — threads the CH client through the PDF parser,
the EDGAR chunker (reused), the embeddings service, and the
``chunks`` table writer.

CONCURRENCY / RETRY MODEL
=========================
Sequential per company (the CH client's token bucket already enforces
2 req/sec). Transient HTTP errors during ``fetch_document`` get one
retry with backoff (1s, 2s, 4s) before we surface.

IDEMPOTENCY
===========
Keyed on ``(company_number, transaction_id)`` — CH's own filing
identifier. We check ``metadata->>'transaction_id'`` before re-ingesting,
so re-running on the same filing is a no-op.

TRUST LEVEL
===========
``firm_vetted`` — Companies House is the UK's statutory filing service.

OFFICERS / CHARGES
==================
Day 4 hard rule: officers and charges go in document metadata only,
not as text chunks. They're list-shaped, not narrative — the analyst
can read them as structured context but they shouldn't compete with
prose for retrieval ranking.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from core.embeddings import embed_texts
from core.retrievers.companies_house.client import CompaniesHouseClient
from core.retrievers.companies_house.parser import parse_pdf
from core.retrievers.companies_house.types import (
    CHFiling,
    CompaniesHouseError,
)
from core.retrievers.edgar.chunker import chunk_filing
from db.connection import acquire
from storage.chunk_queries import insert_chunks

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE: int = 96
_MAX_FETCH_RETRIES: int = 3
_FETCH_BACKOFF_BASE_SECONDS: float = 1.0


@dataclass
class IngestResult:
    """Aggregate return of :func:`ingest_company`."""

    filings_attempted: int = 0
    filings_ingested: int = 0
    filings_skipped_idempotent: int = 0
    filings_skipped_no_text: int = 0
    chunks_written: int = 0
    errors: list[str] = field(default_factory=list)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _transaction_already_ingested(
    company_number: str, transaction_id: str
) -> bool:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM chunks
            WHERE source_type = 'ch_filing'
              AND metadata->>'company_number' = $1
              AND metadata->>'transaction_id' = $2
            LIMIT 1
            """,
            company_number,
            transaction_id,
        )
    return row is not None


async def _fetch_with_retry(client: CompaniesHouseClient, filing: CHFiling) -> bytes:
    last_err: Exception | None = None
    for attempt in range(_MAX_FETCH_RETRIES):
        try:
            return await client.fetch_document(filing)
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt == _MAX_FETCH_RETRIES - 1:
                break
            wait = _FETCH_BACKOFF_BASE_SECONDS * (2**attempt)
            logger.warning(
                "CH fetch failed for %s (attempt %d/%d): %s — retrying in %.1fs",
                filing.transaction_id,
                attempt + 1,
                _MAX_FETCH_RETRIES,
                e,
                wait,
            )
            await asyncio.sleep(wait)
    assert last_err is not None
    raise last_err


# ---------------------------------------------------------------------------
# Per-filing pipeline
# ---------------------------------------------------------------------------


async def _ingest_one_filing(
    client: CompaniesHouseClient,
    *,
    company_number: str,
    company_name: str,
    company_status: str,
    filing: CHFiling,
    session_id: str | None,
    trust_level: str,
    target_chunk_chars: int,
    overlap_chars: int,
) -> tuple[bool, int, str | None]:
    """Run the full pipeline for one filing.

    Returns ``(ingested, chunks_written, error_message)``. Skipped (already
    ingested or empty PDF) returns ``(False, 0, None)``.
    """
    if await _transaction_already_ingested(company_number, filing.transaction_id):
        logger.info(
            "CH ingest: skip %s/%s (already ingested)",
            company_number,
            filing.transaction_id,
        )
        return False, 0, None

    try:
        pdf_bytes = await _fetch_with_retry(client, filing)
    except Exception as e:  # noqa: BLE001
        return False, 0, f"fetch failed: {type(e).__name__}: {e}"

    sections = parse_pdf(pdf_bytes)
    if not sections:
        # PDF either empty or scanned-image (no extractable text). Day 4
        # surface signal — punt rather than write garbage.
        logger.info(
            "CH ingest: %s/%s parsed to zero sections — skipping",
            company_number,
            filing.transaction_id,
        )
        return False, 0, "no extractable text (likely scanned PDF)"

    chunks = chunk_filing(
        sections,
        target_chunk_chars=target_chunk_chars,
        overlap_chars=overlap_chars,
    )
    if not chunks:
        return False, 0, "chunker produced zero chunks"

    contents = [c.content for c in chunks]
    embeddings: list[list[float]] = []
    for i in range(0, len(contents), _EMBED_BATCH_SIZE):
        batch = contents[i : i + _EMBED_BATCH_SIZE]
        try:
            embeddings.extend(await embed_texts(batch))
        except Exception as e:  # noqa: BLE001
            return (
                False,
                0,
                f"embed failed (batch starting at {i}): {type(e).__name__}: {e}",
            )
    if len(embeddings) != len(chunks):
        return False, 0, (
            f"embedding count mismatch: got {len(embeddings)} for {len(chunks)} chunks"
        )

    rows: list[dict[str, Any]] = []
    for pos, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        metadata = {
            "company_number": company_number,
            "company_name": company_name,
            "company_status": company_status,
            "transaction_id": filing.transaction_id,
            "category": filing.category,
            "description": filing.description,
            "filing_date": filing.filing_date,
            "period_end": filing.period_end or "",
            "document_id": filing.document_id,
            "section_canonical_name": chunk.section_canonical_name,
            "item_id": chunk.section_item_id,
            "chunk_index_within_section": chunk.chunk_index_within_section,
            "char_offset_in_filing": chunk.char_offset_in_filing,
        }
        rows.append(
            {
                "content": chunk.content,
                "content_hash": _content_hash(chunk.content),
                "embedding": emb,
                "position": pos,
                "section_heading": (
                    f"{chunk.section_item_id} · {chunk.section_canonical_name}"
                ),
                "metadata": metadata,
            }
        )

    source_filename = f"{company_name} · {filing.description} · {filing.filing_date}"
    written = await insert_chunks(
        session_id=session_id,
        blob_id=None,
        source_file_id=None,
        source_type="ch_filing",
        source_filename=source_filename,
        source_url=(
            f"https://find-and-update.company-information.service.gov.uk/"
            f"company/{company_number}/filing-history/{filing.transaction_id}/"
        ),
        trust_level=trust_level,
        rows=rows,
    )
    return True, len(written), None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def ingest_company(
    *,
    company_number: str | None = None,
    name_or_number: str | None = None,
    limit: int = 1,
    categories: list[str] | None = None,
    session_id: str | None = None,
    trust_level: str = "firm_vetted",
    target_chunk_chars: int = 2000,
    overlap_chars: int = 200,
    client: CompaniesHouseClient | None = None,
) -> IngestResult:
    """Fetch, parse, chunk, embed, write the ``limit`` most recent
    accounts filings for a company.

    Either ``company_number`` (preferred — skips the search step) or
    ``name_or_number`` must be given. ``categories`` defaults to
    ``["accounts"]``.
    """
    if not company_number and not name_or_number:
        raise CompaniesHouseError(
            "ingest_company requires company_number or name_or_number"
        )

    result = IngestResult()
    cats = categories or ["accounts"]
    owns_client = client is None
    ch = client if client is not None else CompaniesHouseClient()
    try:
        # Re-enter the async context only when we own the client; for
        # caller-supplied (test) instances we trust them to manage it.
        if owns_client:
            await ch.__aenter__()
        info = (
            await ch.resolve_company(company_number)
            if company_number
            else await ch.resolve_company(name_or_number or "")
        )
        try:
            filings = await ch.get_filings(info.company_number, categories=cats)
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"get_filings: {type(e).__name__}: {e}")
            return result
        for filing in filings[: int(limit)]:
            result.filings_attempted += 1
            ingested, n, err = await _ingest_one_filing(
                ch,
                company_number=info.company_number,
                company_name=info.company_name,
                company_status=info.company_status,
                filing=filing,
                session_id=session_id,
                trust_level=trust_level,
                target_chunk_chars=target_chunk_chars,
                overlap_chars=overlap_chars,
            )
            if err is not None and "no extractable text" in err:
                result.filings_skipped_no_text += 1
                continue
            if err is not None:
                result.errors.append(f"{filing.transaction_id}: {err}")
                continue
            if ingested:
                result.filings_ingested += 1
                result.chunks_written += n
            else:
                result.filings_skipped_idempotent += 1
        return result
    finally:
        if owns_client:
            await ch.close()
