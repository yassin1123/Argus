"""Earnings-transcript ingest tests (Week 4 / Day 2).

Two paths exercised:

1. **Manual upload (mocked)** — feed the synthetic Apple fixture through
   the manual-upload code path with monkeypatched embeddings + DB write
   stub. Asserts the chunks pass through with the right
   ``source_type='transcript'``, trust level, and metadata shape.

2. **SEC 8-K walker (env-gated)** — the heuristic Day 2 spec called out
   that AAPL/MSFT/TSLA generally don't file transcripts as 8-K Item
   2.02 exhibits. This test runs against the live dev DB only when
   ``ARGUS_RUN_TRANSCRIPT_INTEGRATION=1`` is set so CI doesn't pay for
   it. It asserts the walker either ingests at least one transcript OR
   surfaces zero with no errors (the surface signal — manual upload is
   then the primary path).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from core.retrievers.transcripts import manual_upload as upload_module
from core.retrievers.transcripts.chunker import chunk_transcript

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "transcripts" / "aapl_q4_fy24_synthetic.txt"


@pytest.fixture
def deterministic_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub embed_texts with a 1536-dim hash-based vector (no OpenAI call)."""
    import hashlib

    async def _stub(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            full = (h * (1536 // len(h) + 1))[:1536]
            out.append([(b - 128) / 128.0 for b in full])
        return out

    monkeypatch.setattr(upload_module, "embed_texts", _stub)


@pytest.fixture
def captured_inserts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Stub insert_chunks to capture rows in-memory instead of writing DB."""
    captured: list[dict[str, Any]] = []

    async def _stub(
        *,
        session_id: str | None,
        blob_id: str | None,
        source_file_id: str | None,
        source_type: str,
        source_filename: str,
        source_url: str | None,
        trust_level: str,
        rows: list[dict[str, Any]],
    ) -> list[str]:
        captured.append(
            {
                "session_id": session_id,
                "source_type": source_type,
                "trust_level": trust_level,
                "source_filename": source_filename,
                "source_url": source_url,
                "rows": rows,
            }
        )
        return [f"chunk-{i}" for i in range(len(rows))]

    monkeypatch.setattr(upload_module, "insert_chunks", _stub)
    return captured


async def test_manual_upload_writes_transcript_chunks(
    deterministic_embed,  # noqa: ARG001
    captured_inserts: list[dict[str, Any]],
) -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    outcome = await upload_module.ingest_manual_transcript(
        text=text,
        ticker="AAPL",
        company_name="Apple Inc.",
        quarter="Q4",
        year=2024,
        source_label="manual_test",
        source_path=FIXTURE,
        session_id=None,
    )
    assert outcome["chunks_written"] > 0
    assert outcome["pseudo_accession"].startswith("MANUAL-")
    assert "Tim Cook" in outcome["speakers"]
    assert "Luca Maestri" in outcome["speakers"]

    assert len(captured_inserts) == 1
    call = captured_inserts[0]
    assert call["source_type"] == "transcript"
    assert call["trust_level"] == "general"
    rows = call["rows"]
    assert len(rows) == outcome["chunks_written"]
    sample_meta = rows[0]["metadata"]
    assert sample_meta["ticker"] == "AAPL"
    assert sample_meta["quarter"] == "Q4"
    assert sample_meta["year"] == 2024
    assert sample_meta["accession_number"] == outcome["pseudo_accession"]
    # Every chunk should carry segment + (when speaker known) role.
    for r in rows:
        m = r["metadata"]
        assert m["segment"] in ("prepared_remarks", "qa", "unknown")
        assert "speaker" in m  # may be empty for paragraph-fallback


def test_chunker_handles_vtt_normalised_input() -> None:
    """Smoke-test: VTT cues with <v Name> tags get normalised to speaker
    labels by the upload tool's normaliser, then the chunker can read
    them.
    """
    vtt_raw = (
        "WEBVTT\n\n"
        "1\n"
        "00:00:01.000 --> 00:00:05.000\n"
        "<v Operator>Welcome to the Apple Q4 fiscal year 2024 earnings conference call. "
        "Today's call is being recorded.</v>\n\n"
        "2\n"
        "00:00:06.000 --> 00:00:30.000\n"
        "<v Tim Cook - CEO>Thank you. Today Apple is reporting revenue of 94.9 billion dollars "
        "for our September quarter, up 6 percent year over year.</v>\n\n"
        "3\n"
        "00:00:31.000 --> 00:00:55.000\n"
        "<v Luca Maestri - CFO>Products revenue was 70 billion dollars, with iPhone, Mac, "
        "and iPad all delivering strong year-over-year growth.</v>\n"
    )
    normalised = upload_module.normalise_vtt_or_srt(vtt_raw)
    chunks = chunk_transcript(normalised)
    speakers = {c.speaker for c in chunks}
    assert "Tim Cook" in speakers
    assert "Luca Maestri" in speakers


# ---------------------------------------------------------------------------
# Live-SEC integration — env-gated (Day 2 surface check)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.getenv("ARGUS_RUN_TRANSCRIPT_INTEGRATION") != "1",
    reason="set ARGUS_RUN_TRANSCRIPT_INTEGRATION=1 to run real-API SEC transcript canary",
)
async def test_sec_transcript_walker_real_aapl() -> None:
    """The Day 2 surface check, executed: walk Apple's 4 most recent
    8-K filings; assert no errors and either a transcript landed or none
    matched (the surface signal). Cleans up after itself.
    """
    from core.retrievers.edgar.transcripts import ingest_transcripts_from_8k
    from db.connection import acquire, close_db, init_db

    await init_db()
    try:
        result = await ingest_transcripts_from_8k(ticker="AAPL", limit=4)
        assert result.errors == [], f"unexpected errors: {result.errors}"
        if result.filings_with_transcript_exhibit > 0:
            assert result.chunks_written > 0
            # Cleanup what we just wrote so the test is idempotent.
            async with acquire() as conn:
                await conn.execute(
                    """
                    DELETE FROM chunks
                    WHERE source_type = 'transcript'
                      AND metadata->>'cik' = $1
                      AND metadata->>'source' = 'sec_8k_exhibit'
                    """,
                    "320193",
                )
        else:
            # The surface signal — Day 2 spec called this out.
            assert result.filings_skipped_not_transcript == result.filings_attempted
    finally:
        await close_db()
