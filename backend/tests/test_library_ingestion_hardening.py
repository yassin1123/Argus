"""Phase 3 / Week 14 / Day 2 — library ingestion hardening tests.

Eight tests per spec covering:
  1. Malformed PDF in a batch doesn't fail the batch.
  2. Empty file produces a clear error_reason.
  3. Chunking respects sentence boundaries on long paragraphs.
  4. Table block is not split across chunks.
  5. Hash-dedup skips identical content on the second ingestion.
  6. Per-file IngestionResult shape is populated correctly.
  7. Bulk CLI is idempotent — second run skips all on dedup.
  8. Content-type routing dispatches PDF / DOCX / TXT / CSV correctly.

These tests cover the IN-PROCESS code paths only. Tests that exercise
the live DB live in test_firm_library_service.py and continue to gate
on a running asyncpg pool.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from typing import Any
from unittest import mock

import pytest

from core.firm_library import chunker as library_chunker
from core.firm_library import ingestion as ing
from core.firm_library.chunker import chunk_library_text
from core.firm_library.ingestion import (
    IngestionResult,
    _ingest_single_hardened,
    detect_content_type,
    ingest_files,
    summarise,
)


# ---------------------------------------------------------------------------
# Stubs that bypass the DB + embedding model
# ---------------------------------------------------------------------------


def _patch_db_and_embeddings(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace every DB call + the embed function with in-memory stubs
    so the tests don't need a live Postgres pool."""

    store: dict[str, Any] = {
        "firm_contents": [],   # list of inserted firm_content rows
        "chunk_calls": [],     # list of (firm_content_id, n_chunks)
        "filehash_index": {},  # (firm_id, file_hash) -> firm_content row
    }

    async def fake_find_active(firm_id: str, file_hash: str):
        return store["filehash_index"].get((firm_id, file_hash))

    async def fake_insert_firm_content(*, firm_id, title, category, **kwargs):
        row = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "title": title,
            "category": category,
            "chunk_count": 0,
            "file_hash": kwargs.get("file_hash"),
            "source_filename": kwargs.get("source_filename"),
        }
        store["firm_contents"].append(row)
        store["filehash_index"][(firm_id, kwargs.get("file_hash"))] = row
        return row

    async def fake_insert_chunks(**kwargs):
        rows = kwargs.get("rows") or []
        ids = [str(uuid.uuid4()) for _ in rows]
        store["chunk_calls"].append({
            "firm_content_id": kwargs.get("firm_content_id"),
            "n_chunks": len(rows),
            "rows_preview": rows[:2],
        })
        return ids

    async def fake_update_count(fc_id, count, absolute=True):
        for row in store["firm_contents"]:
            if row["id"] == fc_id:
                row["chunk_count"] = count
                break

    async def fake_embed(texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vec = (h * (1536 // len(h) + 1))[:1536]
            out.append([(b - 128) / 128.0 for b in vec])
        return out

    monkeypatch.setattr(ing, "find_active_by_filehash", fake_find_active)
    monkeypatch.setattr(ing, "insert_firm_content", fake_insert_firm_content)
    monkeypatch.setattr(ing, "insert_chunks", fake_insert_chunks)
    monkeypatch.setattr(ing, "update_chunk_count", fake_update_count)
    monkeypatch.setattr(ing, "embed_texts", fake_embed)
    return store


_TEST_FIRM_ID = "11111111-1111-1111-1111-111111111111"


# ---------------------------------------------------------------------------
# Test 1 — malformed PDF in a batch doesn't fail the batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_pdf_isolated_not_batch_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad PDF must be reported as ``failed`` with a clear reason,
    and the surrounding good files must still ingest cleanly."""
    _patch_db_and_embeddings(monkeypatch)

    good_md = b"# Good doc\n\nThis is a perfectly valid markdown body with enough text to chunk cleanly. " * 20
    bad_pdf = b"this is not a valid pdf"
    second_md = b"# Another doc\n\nAnother body with enough text to land at least one chunk. " * 20

    results = await ingest_files(
        firm_id=_TEST_FIRM_ID,
        files=[("first.md", good_md), ("broken.pdf", bad_pdf), ("third.md", second_md)],
        category="other",
        intended_modes=[],
        sector_tags=[],
    )

    statuses = {r.filename: r.status for r in results}
    assert statuses["first.md"] == "ready"
    assert statuses["broken.pdf"] == "failed"
    assert statuses["third.md"] == "ready"

    bad = next(r for r in results if r.filename == "broken.pdf")
    # The W5 PDF chunker swallows "cannot open" errors and returns an
    # empty list (logs a warning), so we may see either "pdf extractor
    # failed" (if PyMuPDF raised through) OR "0 chunks (...)" (if the
    # chunker logged + returned empty). Both are honest failure reasons
    # — assert that one of the documented forms appears.
    reason = (bad.error_reason or "").lower()
    assert any(
        marker in reason
        for marker in ("pdf extractor failed", "0 chunks", "empty or scanned-only")
    ), f"expected a clear PDF-failure reason, got: {bad.error_reason!r}"


# ---------------------------------------------------------------------------
# Test 2 — empty file produces a clear error_reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_file_produces_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db_and_embeddings(monkeypatch)
    results = await ingest_files(
        firm_id=_TEST_FIRM_ID,
        files=[("empty.md", b""), ("whitespace.md", b"\n\n   \n")],
        category="other",
    )
    assert all(r.status == "failed" for r in results)
    # empty bytes triggers the empty-body guard
    assert "empty file body" in (results[0].error_reason or "").lower()
    # whitespace decodes but the chunker produces 0 chunks → clear reason.
    assert (
        "0 chunks" in (results[1].error_reason or "")
        or "empty string" in (results[1].error_reason or "").lower()
    )


# ---------------------------------------------------------------------------
# Test 3 — chunking respects sentence boundaries on long paragraphs
# ---------------------------------------------------------------------------


def test_chunking_respects_sentence_boundaries() -> None:
    """Build a paragraph longer than the max-chars cap so it has to
    split; assert every chunk ends with sentence-terminating punctuation
    (or is the final chunk)."""
    sentences = [
        f"Sentence number {i} is a clean, well-formed assertion about the topic." for i in range(150)
    ]
    long_para = " ".join(sentences)
    chunks = chunk_library_text(long_para)
    assert len(chunks) >= 2, f"expected multi-chunk split, got {len(chunks)}"

    # Every chunk except the last should end on . ! or ? (sentence boundary).
    for i, c in enumerate(chunks[:-1]):
        last = c.content.rstrip()[-1]
        assert last in ".!?", (
            f"chunk {i} doesn't end on sentence boundary; tail = "
            f"{c.content[-80:]!r}"
        )


# ---------------------------------------------------------------------------
# Test 4 — table block is not split across chunks
# ---------------------------------------------------------------------------


def test_table_not_split_across_chunks() -> None:
    """A markdown table block stays in exactly one chunk regardless of
    its size. We synthesise a long preamble paragraph + a table + a
    long postamble so the chunker has to split somewhere; the split
    must NOT be inside the table."""
    preamble = " ".join(
        f"Preamble sentence number {i} introduces the topic in some detail." for i in range(120)
    )
    table_rows = ["| col_a | col_b | col_c |", "|---|---|---|"]
    for i in range(60):
        table_rows.append(f"| row {i} a | row {i} b | row {i} c |")
    table_text = "\n".join(table_rows)
    postamble = " ".join(
        f"Postamble sentence number {i} draws conclusions from the table." for i in range(120)
    )
    text = preamble + "\n\n" + table_text + "\n\n" + postamble

    chunks = chunk_library_text(text)
    # The full table text should appear in exactly one chunk.
    in_chunk_count = sum(1 for c in chunks if "| row 0 a" in c.content and "| row 59 a" in c.content)
    assert in_chunk_count == 1, (
        f"table was split across chunks (or duplicated): expected exactly 1 chunk "
        f"containing both row 0 and row 59, got {in_chunk_count}. "
        f"Chunk count = {len(chunks)}."
    )


# ---------------------------------------------------------------------------
# Test 5 — hash-dedup skips identical content on the second ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_skips_identical_content(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _patch_db_and_embeddings(monkeypatch)
    body = b"# Doc\n\n" + b"Content that's plenty long enough to land chunks. " * 30
    first = await ingest_files(
        firm_id=_TEST_FIRM_ID,
        files=[("dup.md", body)],
        category="other",
    )
    assert first[0].status == "ready"
    assert first[0].chunks_created >= 1
    n_after_first = len(store["firm_contents"])

    # Re-ingest identical bytes — should hit dedup.
    second = await ingest_files(
        firm_id=_TEST_FIRM_ID,
        files=[("dup.md", body)],
        category="other",
    )
    assert second[0].status == "dedup_skipped"
    assert second[0].dedup_skipped is True
    assert second[0].firm_content_id == first[0].firm_content_id, (
        "dedup should resolve to the same firm_content_id"
    )
    # No new firm_content row should have been inserted on the second call.
    assert len(store["firm_contents"]) == n_after_first


# ---------------------------------------------------------------------------
# Test 6 — IngestionResult shape per file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingestion_result_per_file(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_db_and_embeddings(monkeypatch)
    body = b"# Doc\n\nA short markdown body that will produce chunks. " * 40
    results = await ingest_files(
        firm_id=_TEST_FIRM_ID,
        files=[("shape.md", body)],
        category="other",
    )
    r = results[0]
    assert isinstance(r, IngestionResult)
    assert r.filename == "shape.md"
    assert r.status == "ready"
    assert r.chunks_created >= 1
    assert r.error_reason is None
    assert r.dedup_skipped is False
    assert r.file_hash and len(r.file_hash) == 64        # sha256 hex
    assert r.firm_content_id                              # uuid string
    assert r.extractor == "text"

    rolled = summarise(results)
    assert rolled["total_files"] == 1
    assert rolled["by_status"]["ready"] == 1
    assert rolled["chunks_created"] == r.chunks_created
    assert rolled["failures"] == []


# ---------------------------------------------------------------------------
# Test 7 — bulk CLI is idempotent — second run skips all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_cli_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """``ingest_directory`` is the function the bulk CLI calls. Two
    consecutive runs on the same directory should produce
    [ready, …] then [dedup_skipped, …]."""
    _patch_db_and_embeddings(monkeypatch)

    # Drop a couple of small fixture files into a temp dir.
    d = tmp_path / "lib"
    d.mkdir()
    (d / "a.md").write_text("# A\n\n" + ("This is content A. " * 50), encoding="utf-8")
    (d / "b.md").write_text("# B\n\n" + ("This is content B. " * 50), encoding="utf-8")

    from core.firm_library.ingestion import ingest_directory

    first = await ingest_directory(
        firm_id=_TEST_FIRM_ID,
        directory=d,
        category="other",
        intended_modes=["growth_strategy"],
    )
    assert sorted(r.status for r in first) == ["ready", "ready"]

    second = await ingest_directory(
        firm_id=_TEST_FIRM_ID,
        directory=d,
        category="other",
        intended_modes=["growth_strategy"],
    )
    assert sorted(r.status for r in second) == ["dedup_skipped", "dedup_skipped"]
    # firm_content_ids match between runs (same dedup target).
    by_name_first = {r.filename: r.firm_content_id for r in first}
    by_name_second = {r.filename: r.firm_content_id for r in second}
    assert by_name_first == by_name_second


# ---------------------------------------------------------------------------
# Test 8 — content-type routing dispatches each kind correctly
# ---------------------------------------------------------------------------


def test_content_type_routing() -> None:
    """``detect_content_type`` maps filename → (extractor, unsupported_reason)
    for the documented kinds, and surfaces a clear reason for known-bad
    extensions like .xlsx + .html."""

    # Supported kinds.
    assert detect_content_type("report.pdf") == ("pdf", None)
    assert detect_content_type("notes.docx") == ("docx", None)
    assert detect_content_type("brief.md") == ("text", None)
    assert detect_content_type("brief.txt") == ("text", None)
    assert detect_content_type("deals.csv") == ("csv", None)

    # Case-insensitive.
    assert detect_content_type("UPPER.PDF") == ("pdf", None)

    # Unsupported kinds — extractor is None, reason is set.
    kind, reason = detect_content_type("model.xlsx")
    assert kind is None and reason and "Excel" in reason

    kind, reason = detect_content_type("page.html")
    assert kind is None and reason and "HTML" in reason

    # No extension.
    kind, reason = detect_content_type("README")
    assert kind is None and reason and "missing file extension" in reason
