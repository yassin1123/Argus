"""Walk 8-K filings for transcript-shaped exhibits.

PRIMARY-PATH REALITY (Day 2 surface signal)
==========================================
Empirical check across AAPL Q2-FY26, AAPL Q4-FY25, MSFT Q3-FY26, MSFT
Q2-FY26, TSLA Q4-25 — every Item 2.02 exhibit (Exhibit 99.1) was a
PRESS RELEASE or quarterly slide deck, not a transcript. Public
companies generally post their earnings-call transcripts to their
investor-relations site or third-party services (Seeking Alpha, Motley
Fool) rather than filing them with the SEC.

So this module exists for two reasons:

1. Smaller filers occasionally do file conference-call transcripts as
   8-K Item 2.02 exhibits (Form 425 merger calls also turn up). The
   heuristic below catches those.
2. Idempotent infrastructure — if a future Apple/MSFT filing pattern
   changes, the walker will pick it up automatically.

For Phase 1 the manual-upload path (``tools/transcript_upload.py``) is
the workhorse for AAPL/MSFT/TSLA. The SEC walker stays as
defence-in-depth + future-proofing.

HEURISTIC
=========
Per Day 2 spec: > 5000 chars (raw text after HTML strip) AND contains
at least two transcript-tells: 'Operator', 'Q&A',
'thank you for joining', 'prepared remarks', 'Question-and-Answer',
'Conference Call', 'thank you, everyone, for joining'. Plus the
post-tier check that ``detect_speaker_turn_format`` returns True (i.e.
3+ distinct speaker labels). A bare press release will fail the
last tier even if it mentions "Operator" once.

INGEST
======
Identical schema to ``core.retrievers.edgar.ingest`` (chunks table with
``source_type='transcript'`` instead of ``'sec_filing'``). Idempotency
keyed on ``metadata->>'accession_number'``. Trust level
``'firm_vetted'`` because the source is SEC-attached.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from core.embeddings import embed_texts
from core.retrievers.edgar.client import EdgarClient
from core.retrievers.edgar.types import EdgarError, Filing
from core.retrievers.transcripts.chunker import (
    chunk_transcript,
    detect_speaker_turn_format,
)
from db.connection import acquire
from storage.chunk_queries import insert_chunks

logger = logging.getLogger(__name__)

_MIN_TRANSCRIPT_CHARS: int = 5000
_TRANSCRIPT_KEYWORDS: tuple[str, ...] = (
    "operator",
    "q&a",
    "q & a",
    "question-and-answer",
    "prepared remarks",
    "thank you for joining",
    "conference call",
    "thank you, everyone",
)
_MIN_KEYWORD_HITS: int = 2

_EMBED_BATCH_SIZE: int = 96
_EXHIBIT_NAME_RE = re.compile(
    r"(ex[-_ ]?99|exhibit[-_ ]?99|99[._]1)", re.IGNORECASE
)


@dataclass
class TranscriptIngestResult:
    """Aggregate return of :func:`ingest_transcripts_from_8k`."""

    filings_attempted: int = 0
    filings_with_transcript_exhibit: int = 0
    filings_skipped_idempotent: int = 0
    filings_skipped_not_transcript: int = 0
    chunks_written: int = 0
    errors: list[str] = field(default_factory=list)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_html(html: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&#x?[0-9a-f]+;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"&[a-z]+;", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _looks_like_transcript(text: str) -> bool:
    """Apply the Day 2 heuristic: length + keyword density + speaker turns."""
    if len(text) < _MIN_TRANSCRIPT_CHARS:
        return False
    lower = text.lower()
    hits = sum(1 for kw in _TRANSCRIPT_KEYWORDS if kw in lower)
    if hits < _MIN_KEYWORD_HITS:
        return False
    return detect_speaker_turn_format(text)


async def _accession_already_ingested(accession_number: str) -> bool:
    """Idempotency check — same shape as the EDGAR primary-doc path."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM chunks
            WHERE source_type = 'transcript'
              AND metadata->>'accession_number' = $1
            LIMIT 1
            """,
            accession_number,
        )
    return row is not None


async def _list_exhibit_candidates(client: EdgarClient, filing: Filing) -> list[str]:
    """Return URLs of plausibly-transcript exhibit files in this filing.

    Uses the SEC filing-index JSON (``index.json``) listing every file in
    the accession directory, then filters by name pattern (Exhibit 99.x).
    Returns same-origin URLs.
    """
    if not filing.primary_doc_url:
        return []
    base = filing.primary_doc_url.rsplit("/", 1)[0] + "/"
    try:
        resp = await client._client.get(base + "index.json")  # noqa: WPS437
        items = (resp.json().get("directory") or {}).get("item") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("filing-index fetch failed for %s: %s", filing.accession_number, e)
        return []
    out: list[str] = []
    for it in items:
        name = str(it.get("name") or "")
        if not _EXHIBIT_NAME_RE.search(name):
            continue
        if not name.lower().endswith((".htm", ".html", ".txt")):
            continue
        out.append(base + name)
    return out


async def _ingest_one_transcript_exhibit(
    client: EdgarClient,
    *,
    cik: str,
    company_name: str,
    filing: Filing,
    exhibit_url: str,
    exhibit_text: str,
    session_id: str | None,
    trust_level: str,
) -> tuple[int, str | None]:
    """Chunk + embed + write one verified transcript exhibit."""
    chunks = chunk_transcript(exhibit_text)
    if not chunks:
        return 0, "chunker produced zero chunks"

    contents = [c.content for c in chunks]
    embeddings: list[list[float]] = []
    for i in range(0, len(contents), _EMBED_BATCH_SIZE):
        batch = contents[i : i + _EMBED_BATCH_SIZE]
        try:
            batch_embeds = await embed_texts(batch)
        except Exception as e:  # noqa: BLE001
            return 0, f"embed failed (batch starting at {i}): {type(e).__name__}: {e}"
        embeddings.extend(batch_embeds)
    if len(embeddings) != len(chunks):
        return 0, f"embedding count mismatch: got {len(embeddings)} for {len(chunks)} chunks"

    rows: list[dict[str, Any]] = []
    for pos, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        metadata = {
            "cik": cik,
            "company_name": company_name,
            "form": filing.form,
            "accession_number": filing.accession_number,
            "filing_date": filing.filing_date,
            "report_date": filing.report_date or "",
            "exhibit_url": exhibit_url,
            "speaker": chunk.speaker,
            "role": chunk.role,
            "firm": chunk.firm,
            "segment": chunk.segment,
            "turn_index": chunk.turn_index,
            "char_offset_in_transcript": chunk.char_offset_in_transcript,
            "source": "sec_8k_exhibit",
        }
        rows.append(
            {
                "content": chunk.content,
                "content_hash": _content_hash(chunk.content),
                "embedding": emb,
                "position": pos,
                "section_heading": (
                    f"{chunk.segment} · {chunk.speaker}" if chunk.speaker else chunk.segment
                ),
                "metadata": metadata,
            }
        )

    source_filename = f"Earnings call · {filing.filing_date} · {company_name}"
    written = await insert_chunks(
        session_id=session_id,
        blob_id=None,
        source_file_id=None,
        source_type="transcript",
        source_filename=source_filename,
        source_url=exhibit_url,
        trust_level=trust_level,
        rows=rows,
    )
    return len(written), None


async def ingest_transcripts_from_8k(
    *,
    cik: str | None = None,
    ticker: str | None = None,
    limit: int = 4,
    session_id: str | None = None,
    trust_level: str = "firm_vetted",
    client: EdgarClient | None = None,
) -> TranscriptIngestResult:
    """Walk the most recent ``limit`` 8-K filings for the given filer and
    ingest any that carry a transcript-shaped Item 2.02 exhibit.

    ``limit`` defaults to 4 per Day 2 hard rule (politeness toward sec.gov).
    Either ``cik`` or ``ticker`` must be given.
    """
    if cik is None and ticker is None:
        raise EdgarError("ingest_transcripts_from_8k requires cik or ticker")
    result = TranscriptIngestResult()
    owns = client is None
    edgar = client if client is not None else EdgarClient()
    try:
        if cik is None:
            assert ticker is not None
            info = await edgar.resolve_ticker(ticker)
            cik = info.cik
            company_name = info.name
        else:
            try:
                async with EdgarClient() as helper:
                    table = await helper._load_tickers_table()  # noqa: WPS437
                company_name = next(
                    (v.name for v in table.values() if v.cik == cik), ""
                )
            except Exception:
                company_name = ""

        try:
            filings = await edgar.list_filings(cik, forms=["8-K"], limit=limit)
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"list_filings(8-K): {type(e).__name__}: {e}")
            return result

        for filing in filings:
            result.filings_attempted += 1
            if await _accession_already_ingested(filing.accession_number):
                result.filings_skipped_idempotent += 1
                continue

            exhibit_urls = await _list_exhibit_candidates(edgar, filing)
            picked_url: str | None = None
            picked_text: str = ""
            for url in exhibit_urls:
                try:
                    resp = await edgar._client.get(url)  # noqa: WPS437
                except Exception as e:  # noqa: BLE001
                    result.errors.append(f"{filing.accession_number}: fetch {url}: {e}")
                    continue
                text = _strip_html(resp.text)
                if _looks_like_transcript(text):
                    picked_url = url
                    picked_text = text
                    break

            if not picked_url:
                result.filings_skipped_not_transcript += 1
                continue

            result.filings_with_transcript_exhibit += 1
            n, err = await _ingest_one_transcript_exhibit(
                edgar,
                cik=cik,
                company_name=company_name,
                filing=filing,
                exhibit_url=picked_url,
                exhibit_text=picked_text,
                session_id=session_id,
                trust_level=trust_level,
            )
            if err is not None:
                result.errors.append(f"{filing.accession_number}: {err}")
                continue
            result.chunks_written += n
        return result
    finally:
        if owns:
            await edgar.close()
