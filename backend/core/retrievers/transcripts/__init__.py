"""Earnings-call transcript retrieval (Phase 1 / Week 4 / Day 2).

Speaker-turn-aware chunker that handles two input shapes:

  - Prepared-remarks-then-Q&A transcripts (Apple / Microsoft / Tesla
    style): "Operator:", "Tim Cook - CEO:", "Wamsi Mohan - Bank of
    America:", etc. We detect speaker turns by regex and emit one chunk
    per speaker turn, with a context window of 2 prior turns prepended
    to each Q&A turn so the question's chunk includes the analyst's
    setup.
  - Plain narrative paragraphs (e.g. summary articles, AI-generated
    transcripts without speaker labels): we fall back to paragraph-aware
    chunking similar to ``core.retrievers.edgar.chunker``.

Two ingestion paths feed this module:

  - ``core.retrievers.edgar.transcripts`` walks 8-K Item 2.02 exhibits
    on SEC EDGAR. Reality check (Day 2 surface): for AAPL / MSFT / TSLA
    these are press releases, not transcripts — the Day 2 spec called
    this out and the manual-upload path is the primary one until / unless
    a smaller filer happens to publish a transcript exhibit.
  - ``tools.transcript_upload`` accepts plain TXT / VTT / SRT files with
    --ticker / --quarter / --year / --source metadata. This is the
    workhorse for the three Phase 1 tickers.

Schema:
  - source_type='transcript'
  - trust_level='firm_vetted' (SEC) or 'general' (manual upload)
  - metadata={ticker, company_name, quarter, year, source, speaker, role,
              segment ('prepared_remarks' | 'qa'),
              turn_index, total_turns, accession_number (SEC only)}
"""

from core.retrievers.transcripts.chunker import (
    TranscriptChunk,
    chunk_transcript,
    detect_speaker_turn_format,
)

__all__ = [
    "TranscriptChunk",
    "chunk_transcript",
    "detect_speaker_turn_format",
]
