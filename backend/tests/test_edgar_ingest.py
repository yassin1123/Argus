"""SEC EDGAR ingestion tests (Week 3 / Day 3).

Four mocked tests use httpx.MockTransport for sec.gov + monkeypatched
``embed_texts`` for OpenAI; they hit the live dev Postgres but isolate
their writes via a unique-per-test ``cik``/``accession_number`` so
parallel runs and re-runs stay clean.

One integration test (gated by ``ARGUS_RUN_EDGAR_INTEGRATION=1``) does
the full live path: real sec.gov fetch + real OpenAI embeddings + DB
write.
"""

from __future__ import annotations

import gzip
import json
import os
import uuid
import warnings
from pathlib import Path
from typing import Any

import httpx
import pytest

from core.retrievers.edgar import EdgarClient, ingest_filings
from core.retrievers.edgar import ingest as ingest_module

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "edgar"


@pytest.fixture(autouse=True)
async def _db_pool():
    """Initialise the asyncpg pool for the duration of each test.

    The ingest tests do real DB writes; without this fixture acquire()
    fails with "Database pool not initialized". Per-test scope keeps
    each test's DB connection clean.
    """
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


# ---------------------------------------------------------------------------
# Mock infra: a synthetic CIK + tickers table + fake submissions JSON
# pointing at the committed AAPL 10-K HTML fixture.
# ---------------------------------------------------------------------------


def _fake_synthetic_filings(cik_padded: str, accession: str) -> dict[str, Any]:
    return {
        "cik": cik_padded.lstrip("0") or "0",
        "name": "TestCo Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [accession],
                "filingDate": ["2025-09-30"],
                "reportDate": ["2025-09-30"],
                "form": ["10-K"],
                "primaryDocument": ["test-20250930.htm"],
            }
        },
    }


def _make_mock_transport(*, cik_int: int, accession: str):
    cik_padded = f"{cik_int:010d}"
    fixture_html = (FIXTURE_DIR / "aapl_10k_2024.html.gz").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/files/company_tickers.json"):
            return httpx.Response(
                200,
                json={"0": {"cik_str": cik_int, "ticker": "TEST", "title": "TestCo Inc."}},
            )
        if "/submissions/CIK" in url:
            return httpx.Response(200, json=_fake_synthetic_filings(cik_padded, accession))
        if "/Archives/edgar/data/" in url:
            # gunzip and serve as text/html
            return httpx.Response(
                200,
                content=gzip.decompress(fixture_html),
                headers={"content-type": "text/html; charset=utf-8"},
            )
        return httpx.Response(404, text=f"unmocked: {url}")

    return httpx.MockTransport(handler)


def _stub_embed_texts():
    """Return an async stub that produces a 1536-dim deterministic vector
    per input text (sha256 hash bytes truncated, normalised) — fast + no
    OpenAI call. Each text always maps to the same vector so the chunks
    table comes back consistent across re-runs.
    """
    import hashlib

    async def _stub(texts):
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            # Spread the hash across 1536 dimensions: tile + scale to [-1, 1]
            full = (h * (1536 // len(h) + 1))[:1536]
            out.append([(b - 128) / 128.0 for b in full])
        return out

    return _stub


# Synthetic CIK + accession per test so each run is isolated and the
# test can cleanly verify "this exact chunk was written".


@pytest.fixture
async def cleanup_chunks():
    """Yield a callable that records accession_numbers to delete after the test."""
    accessions: list[str] = []
    yield accessions
    if not accessions:
        return
    from db.connection import acquire

    async with acquire() as conn:
        await conn.execute(
            """
            DELETE FROM chunks
            WHERE source_type = 'sec_filing'
              AND metadata->>'accession_number' = ANY($1::text[])
            """,
            accessions,
        )


# ---------------------------------------------------------------------------
# Mocked tests
# ---------------------------------------------------------------------------


async def test_ingest_writes_chunks_with_correct_metadata(monkeypatch, cleanup_chunks) -> None:
    cik_int = 990001
    accession = f"0000{cik_int}-99-{uuid.uuid4().hex[:6].upper()}"
    cleanup_chunks.append(accession)

    monkeypatch.setattr(ingest_module, "embed_texts", _stub_embed_texts())
    transport = _make_mock_transport(cik_int=cik_int, accession=accession)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        async with EdgarClient(transport=transport) as edgar:
            result = await ingest_filings(
                ticker="TEST",
                forms=["10-K"],
                limit_per_form=1,
                client=edgar,
            )

    assert result.filings_attempted == 1
    assert result.filings_ingested == 1
    assert result.chunks_written > 0
    assert not result.errors

    # Verify what landed in the chunks table.
    from db.connection import acquire

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT content, source_type, source_filename, source_url, trust_level,
                   session_id, metadata, section_heading
            FROM chunks
            WHERE source_type = 'sec_filing'
              AND metadata->>'accession_number' = $1
            ORDER BY position ASC
            """,
            accession,
        )
    assert len(rows) == result.chunks_written
    sample = rows[0]
    assert sample["source_type"] == "sec_filing"
    assert sample["trust_level"] == "firm_vetted"
    assert sample["session_id"] is None  # firm-global
    assert "TestCo" in sample["source_filename"]
    assert sample["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/")
    metadata = sample["metadata"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    expected_keys = {
        "cik",
        "company_name",
        "form",
        "accession_number",
        "filing_date",
        "report_date",
        "item_id",
        "section_canonical_name",
        "chunk_index_within_section",
        "char_offset_in_filing",
        "primary_doc_url",
    }
    assert expected_keys.issubset(metadata.keys()), (
        f"metadata missing keys: {expected_keys - set(metadata.keys())}"
    )
    assert metadata["accession_number"] == accession
    assert metadata["form"] == "10-K"
    # section_heading mirrors the metadata for retriever-side display.
    assert sample["section_heading"]
    assert metadata["item_id"] in sample["section_heading"]


async def test_ingest_idempotent(monkeypatch, cleanup_chunks) -> None:
    cik_int = 990002
    accession = f"0000{cik_int}-99-{uuid.uuid4().hex[:6].upper()}"
    cleanup_chunks.append(accession)

    monkeypatch.setattr(ingest_module, "embed_texts", _stub_embed_texts())
    transport = _make_mock_transport(cik_int=cik_int, accession=accession)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        async with EdgarClient(transport=transport) as edgar:
            first = await ingest_filings(
                ticker="TEST", forms=["10-K"], limit_per_form=1, client=edgar
            )
        async with EdgarClient(transport=transport) as edgar:
            second = await ingest_filings(
                ticker="TEST", forms=["10-K"], limit_per_form=1, client=edgar
            )

    assert first.filings_ingested == 1
    assert first.chunks_written > 0
    # Second run sees the same accession_number already present.
    assert second.filings_ingested == 0
    assert second.filings_skipped_idempotent == 1
    assert second.chunks_written == 0
    # Total chunks in DB should equal the first run only.
    from db.connection import acquire

    async with acquire() as conn:
        n = await conn.fetchval(
            """
            SELECT count(*) FROM chunks
            WHERE source_type = 'sec_filing'
              AND metadata->>'accession_number' = $1
            """,
            accession,
        )
    assert n == first.chunks_written


async def test_ingest_handles_unknown_section(monkeypatch, cleanup_chunks) -> None:
    """When the parser's UNKNOWN bucket fires (or cover_page does), those
    chunks still get written with their item_id intact in metadata.
    """
    cik_int = 990003
    accession = f"0000{cik_int}-99-{uuid.uuid4().hex[:6].upper()}"
    cleanup_chunks.append(accession)

    monkeypatch.setattr(ingest_module, "embed_texts", _stub_embed_texts())
    transport = _make_mock_transport(cik_int=cik_int, accession=accession)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        async with EdgarClient(transport=transport) as edgar:
            await ingest_filings(
                ticker="TEST", forms=["10-K"], limit_per_form=1, client=edgar
            )

    from db.connection import acquire

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT metadata->>'item_id' AS item_id
            FROM chunks
            WHERE source_type = 'sec_filing'
              AND metadata->>'accession_number' = $1
            """,
            accession,
        )
    item_ids = {r["item_id"] for r in rows}
    # cover_page (front matter) is always present in a real 10-K.
    assert "cover_page" in item_ids, f"expected cover_page in {item_ids}"
    # No item_id should be NULL.
    assert None not in item_ids


async def test_ingest_metadata_carries_chunk_breadcrumbs(monkeypatch, cleanup_chunks) -> None:
    """Each chunk's metadata should carry chunk_index_within_section +
    char_offset_in_filing so the retriever can produce deep-link
    citations like "Item 1A · chunk 7 · offset 38421".
    """
    cik_int = 990004
    accession = f"0000{cik_int}-99-{uuid.uuid4().hex[:6].upper()}"
    cleanup_chunks.append(accession)

    monkeypatch.setattr(ingest_module, "embed_texts", _stub_embed_texts())
    transport = _make_mock_transport(cik_int=cik_int, accession=accession)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        async with EdgarClient(transport=transport) as edgar:
            await ingest_filings(
                ticker="TEST", forms=["10-K"], limit_per_form=1, client=edgar
            )

    from db.connection import acquire

    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT metadata
            FROM chunks
            WHERE source_type = 'sec_filing'
              AND metadata->>'accession_number' = $1
            ORDER BY position ASC
            """,
            accession,
        )
    assert rows
    for row in rows:
        m = row["metadata"]
        if isinstance(m, str):
            m = json.loads(m)
        assert isinstance(m.get("chunk_index_within_section"), int)
        assert isinstance(m.get("char_offset_in_filing"), int)
        assert m["char_offset_in_filing"] >= 0


# ---------------------------------------------------------------------------
# Integration canary — only with ARGUS_RUN_EDGAR_INTEGRATION=1
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("ARGUS_RUN_EDGAR_INTEGRATION") != "1",
    reason="set ARGUS_RUN_EDGAR_INTEGRATION=1 to run real-API ingest canary",
)
async def test_ingest_real_apple_10k(cleanup_chunks) -> None:
    """Full ingestion of Apple's most recent 10-K via real sec.gov +
    real OpenAI embeddings. Bounded politely to a single 10-K. Cleans
    up after itself via the cleanup_chunks fixture.
    """
    # We don't know the accession_number ahead of time, but cleanup_chunks
    # accepts any list — append after the run.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = await ingest_filings(
            ticker="AAPL",
            forms=["10-K"],
            limit_per_form=1,
        )
    assert result.errors == [] or all("idempotent" in e.lower() for e in result.errors)
    # If the run skipped because it was already ingested, that's fine —
    # the path under test still exercised the resolve + list_filings
    # checks.
    if result.filings_ingested > 0:
        assert result.chunks_written >= 50, (
            f"Apple 10-K should produce many chunks; got {result.chunks_written}"
        )
        # Capture what we just wrote for cleanup.
        from db.connection import acquire

        async with acquire() as conn:
            accs = await conn.fetch(
                """
                SELECT DISTINCT metadata->>'accession_number' AS acc
                FROM chunks
                WHERE source_type = 'sec_filing'
                  AND metadata->>'company_name' = 'Apple Inc.'
                  AND metadata->>'form' = '10-K'
                """
            )
        for row in accs:
            cleanup_chunks.append(row["acc"])
