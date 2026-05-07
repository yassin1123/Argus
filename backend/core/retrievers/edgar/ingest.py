"""End-to-end SEC EDGAR ingestion pipeline.

Phase 1 / Week 3 / Day 3. One async function — :func:`ingest_filings` —
threads Day 1's ``EdgarClient`` through Day 2's parser + chunker, embeds
the chunks via the existing ``core.embeddings.embed_texts`` path, and
writes them to the ``chunks`` table with full SEC breadcrumb metadata
so downstream retrieval can produce citations like
"Apple 10-K (2025-09-27), Item 1A · chunk 7".

CONCURRENCY / RETRY MODEL
=========================
- Each filing is processed sequentially per company (the EdgarClient's
  internal token bucket already enforces sec.gov's 10/sec cap, so
  serialisation here keeps the request stream simple and predictable).
- Transient sec.gov errors (timeouts, 5xx, rate-limit blips) are
  retried with exponential backoff: 1s, 2s, 4s, then surface. The
  parser / chunker / DB-write stages are deterministic so the retry
  only wraps the network fetch.

IDEMPOTENCY
===========
- ``accession_number`` is the unique-per-filing key. We check the
  ``metadata->>'accession_number'`` partial index added in migration
  022 to skip already-ingested filings without rewriting their chunks.
- We do NOT dedupe at chunk level. Accession-level is enough — re-
  parsing the same filing produces the same chunks, so re-running
  ingest doesn't change the data set even if dedupe missed.

SESSION HANDLING
================
- SEC content is firm-global by default: chunks are written with
  ``session_id = NULL`` and ``trust_level = 'firm_vetted'``. The
  schema's session_id NOT NULL constraint was relaxed in migration 023
  specifically to enable this.
- Callers can pass ``session_id`` to scope chunks to one engagement
  (useful for "vault-only" runs or per-firm curation).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from core.embeddings import embed_texts
from core.retrievers.edgar.chunker import chunk_filing
from core.retrievers.edgar.client import EdgarClient
from core.retrievers.edgar.parser import parse_filing_sections
from core.retrievers.edgar.types import EdgarError, Filing
from db.connection import acquire
from storage.chunk_queries import insert_chunks

logger = logging.getLogger(__name__)

# Embedding batch size — OpenAI text-embedding-3-small accepts up to
# 2048 inputs per call. We stay well under that for safety + so a
# transient failure on one batch doesn't lose a whole filing's chunks.
_EMBED_BATCH_SIZE: int = 96

# Retry policy for sec.gov fetches.
_MAX_FETCH_RETRIES: int = 3
_FETCH_BACKOFF_BASE_SECONDS: float = 1.0


@dataclass
class IngestResult:
    """Aggregate return of :func:`ingest_filings`.

    Attributes
    ----------
    filings_attempted:
        Number of filings the pipeline tried to ingest (after applying
        per-form limit).
    filings_ingested:
        Filings that wrote at least one chunk on this run.
    filings_skipped_idempotent:
        Filings already present in the chunks table (matched by
        accession_number); zero chunks written, not an error.
    chunks_written:
        Total chunks inserted across all filings on this run.
    chunks_skipped:
        Reserved for future per-chunk dedupe; always 0 today.
    errors:
        List of "{accession_number}: {error}" strings — one per
        filing that failed both fetch and retry. Other filings
        keep ingesting; this is best-effort.
    """

    filings_attempted: int = 0
    filings_ingested: int = 0
    filings_skipped_idempotent: int = 0
    chunks_written: int = 0
    chunks_skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _accession_already_ingested(accession_number: str) -> bool:
    """Idempotency check: any SEC chunk with this accession_number?"""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1
            FROM chunks
            WHERE source_type = 'sec_filing'
              AND metadata->>'accession_number' = $1
            LIMIT 1
            """,
            accession_number,
        )
    return row is not None


async def _fetch_with_retry(client: EdgarClient, filing: Filing):
    """Fetch the primary doc with exponential backoff on transient errors."""
    last_error: Exception | None = None
    for attempt in range(_MAX_FETCH_RETRIES):
        try:
            return await client.fetch_document(filing)
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt == _MAX_FETCH_RETRIES - 1:
                break
            wait = _FETCH_BACKOFF_BASE_SECONDS * (2**attempt)
            logger.warning(
                "EDGAR fetch failed for %s (attempt %d/%d): %s — retrying in %.1fs",
                filing.accession_number,
                attempt + 1,
                _MAX_FETCH_RETRIES,
                e,
                wait,
            )
            await asyncio.sleep(wait)
    assert last_error is not None
    raise last_error


# ---------------------------------------------------------------------------
# Per-filing pipeline
# ---------------------------------------------------------------------------


async def _ingest_one_filing(
    client: EdgarClient,
    *,
    cik: str,
    company_name: str,
    filing: Filing,
    session_id: str | None,
    trust_level: str,
    target_chunk_chars: int,
    overlap_chars: int,
) -> tuple[bool, int, str | None]:
    """Run the full pipeline for one filing.

    Returns ``(ingested, chunks_written, error_message)``. Skipped (already
    ingested) is reported as ``(False, 0, None)``; an exception is reported
    as ``(False, 0, "<error>")``.
    """
    if await _accession_already_ingested(filing.accession_number):
        logger.info(
            "EDGAR ingest: skip %s %s (already ingested)",
            filing.form,
            filing.accession_number,
        )
        return False, 0, None

    try:
        doc = await _fetch_with_retry(client, filing)
    except Exception as e:  # noqa: BLE001
        return False, 0, f"fetch failed: {type(e).__name__}: {e}"

    sections = parse_filing_sections(doc.raw_html, filing.form)
    chunks = chunk_filing(
        sections,
        target_chunk_chars=target_chunk_chars,
        overlap_chars=overlap_chars,
    )
    if not chunks:
        return False, 0, "parser produced zero chunks"

    # Embed in batches.
    contents = [c.content for c in chunks]
    embeddings: list[list[float]] = []
    for i in range(0, len(contents), _EMBED_BATCH_SIZE):
        batch = contents[i : i + _EMBED_BATCH_SIZE]
        try:
            batch_embeds = await embed_texts(batch)
        except Exception as e:  # noqa: BLE001
            return (
                False,
                0,
                f"embed failed (batch starting at {i}): {type(e).__name__}: {e}",
            )
        embeddings.extend(batch_embeds)
    if len(embeddings) != len(chunks):
        return (
            False,
            0,
            f"embedding count mismatch: got {len(embeddings)} for {len(chunks)} chunks",
        )

    rows: list[dict[str, Any]] = []
    for pos, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        # Layered breadcrumbs so the verifier can produce citations like
        # "Apple 10-K (2025-09-27), Item 1A · chunk 7" + a deep link.
        metadata = {
            "cik": cik,
            "company_name": company_name,
            "form": filing.form,
            "accession_number": filing.accession_number,
            "filing_date": filing.filing_date,
            "report_date": filing.report_date or "",
            "item_id": chunk.section_item_id,
            "section_canonical_name": chunk.section_canonical_name,
            "chunk_index_within_section": chunk.chunk_index_within_section,
            "char_offset_in_filing": chunk.char_offset_in_filing,
            "primary_doc_url": filing.primary_doc_url,
        }
        rows.append(
            {
                "content": chunk.content,
                "content_hash": _content_hash(chunk.content),
                "embedding": emb,
                "position": pos,
                # Reuse the typed columns where they fit so the
                # existing retriever (which doesn't yet read metadata
                # jsonb) still surfaces useful labels.
                "section_heading": f"{chunk.section_item_id} · {chunk.section_canonical_name}",
                "metadata": metadata,
            }
        )

    source_filename = f"{filing.form} · {filing.filing_date} · {company_name}"
    written = await insert_chunks(
        session_id=session_id,
        blob_id=None,
        source_file_id=None,
        source_type="sec_filing",
        source_filename=source_filename,
        source_url=filing.primary_doc_url,
        trust_level=trust_level,
        rows=rows,
    )
    return True, len(written), None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def ingest_filings(
    *,
    cik: str | None = None,
    ticker: str | None = None,
    forms: list[str] | None = None,
    limit_per_form: int = 1,
    session_id: str | None = None,
    trust_level: str = "firm_vetted",
    target_chunk_chars: int = 2000,
    overlap_chars: int = 200,
    client: EdgarClient | None = None,
) -> IngestResult:
    """Fetch -> parse -> chunk -> embed -> write to ``chunks`` for every
    filing matching ``forms`` (cap ``limit_per_form`` per form).

    Either ``cik`` or ``ticker`` must be given. ``forms`` defaults to
    ``["10-K", "10-Q", "8-K", "DEF 14A", "S-1"]``. ``client`` lets
    callers (notably tests) inject a pre-built EdgarClient with a mock
    transport; otherwise we open one with the default config.
    """
    if cik is None and ticker is None:
        raise EdgarError("ingest_filings requires either cik or ticker")
    forms = list(forms) if forms else ["10-K", "10-Q", "8-K", "DEF 14A", "S-1"]
    result = IngestResult()

    owns_client = client is None
    edgar = client if client is not None else EdgarClient()
    try:
        if cik is None:
            assert ticker is not None
            info = await edgar.resolve_ticker(ticker)
            cik = info.cik
            company_name = info.name
        else:
            # Caller passed a CIK — best-effort resolve to a name for
            # nicer source labels. A failure here is non-fatal.
            try:
                async with EdgarClient() as helper:
                    table = await helper._load_tickers_table()  # noqa: WPS437
                company_name = next(
                    (v.name for v in table.values() if v.cik == cik), ""
                )
            except Exception:
                company_name = ""

        for form in forms:
            try:
                filings = await edgar.list_filings(cik, forms=[form], limit=limit_per_form)
            except Exception as e:  # noqa: BLE001
                result.errors.append(f"list_filings({form}): {type(e).__name__}: {e}")
                continue
            for filing in filings:
                result.filings_attempted += 1
                ingested, n, err = await _ingest_one_filing(
                    edgar,
                    cik=cik,
                    company_name=company_name,
                    filing=filing,
                    session_id=session_id,
                    trust_level=trust_level,
                    target_chunk_chars=target_chunk_chars,
                    overlap_chars=overlap_chars,
                )
                if err is not None:
                    result.errors.append(f"{filing.accession_number}: {err}")
                    continue
                if ingested:
                    result.filings_ingested += 1
                    result.chunks_written += n
                else:
                    result.filings_skipped_idempotent += 1
        return result
    finally:
        if owns_client:
            await edgar.close()
