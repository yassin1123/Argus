"""Speaker-turn chunker tests (Week 4 / Day 2).

Validates parser shape against the synthetic Apple Q4 FY24 fixture
(speaker-labelled Operator → prepared remarks → Q&A) plus paragraph-
fallback behaviour on plain-text input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.retrievers.transcripts.chunker import (
    chunk_transcript,
    detect_speaker_turn_format,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "transcripts"
AAPL_Q4_FY24 = FIXTURE_DIR / "aapl_q4_fy24_synthetic.txt"


def _read_fixture() -> str:
    return AAPL_Q4_FY24.read_text(encoding="utf-8")


def test_speaker_turn_format_detected() -> None:
    text = _read_fixture()
    assert detect_speaker_turn_format(text) is True


def test_chunks_have_correct_speaker_metadata() -> None:
    chunks = chunk_transcript(_read_fixture())
    assert chunks, "expected at least one chunk"
    speakers = [c.speaker for c in chunks]
    # The fixture has ~10 substantive turns; short Operator turns get folded.
    assert "Tim Cook" in speakers
    assert "Luca Maestri" in speakers
    assert "Erik Woodring" in speakers
    assert "Wamsi Mohan" in speakers
    assert "Krish Sankar" in speakers


def test_role_inference_fills_known_officers() -> None:
    chunks = chunk_transcript(_read_fixture())
    # Tim Cook's turn label was "Tim Cook - CEO:" so role is parsed
    # directly. Luca's was "Luca Maestri - CFO:" — same. We assert that
    # both have non-empty roles regardless of source.
    by_speaker = {c.speaker: c for c in chunks}
    assert by_speaker["Tim Cook"].role == "CEO"
    assert by_speaker["Luca Maestri"].role == "CFO"


def test_qa_section_detected_and_segments_classified() -> None:
    chunks = chunk_transcript(_read_fixture())
    prepared = [c for c in chunks if c.segment == "prepared_remarks"]
    qa = [c for c in chunks if c.segment == "qa"]
    assert prepared, "expected at least one prepared_remarks chunk"
    assert qa, "expected at least one qa chunk"
    # All analyst-firm-affiliated speakers should land in qa.
    for c in chunks:
        if c.firm:
            assert c.segment == "qa", (
                f"speaker '{c.speaker}' affiliated with firm '{c.firm}' "
                f"should be qa, got {c.segment}"
            )
    # Tim's opening prepared-remarks turn precedes the Q&A boundary.
    tim_prepared = next((c for c in chunks if c.speaker == "Tim Cook" and c.segment == "prepared_remarks"), None)
    assert tim_prepared is not None


def test_qa_chunks_carry_context_prefix() -> None:
    chunks = chunk_transcript(_read_fixture())
    qa = [c for c in chunks if c.segment == "qa"]
    # At least one qa chunk should have a non-empty context_prefix
    # (the analyst's question that the answer is responding to).
    with_ctx = [c for c in qa if c.context_prefix]
    assert with_ctx, "expected at least one qa chunk to carry context_prefix"
    # The context window should mention a prior speaker.
    for c in with_ctx:
        assert "[CONTEXT" in c.content


def test_operator_turns_are_never_emitted_standalone() -> None:
    """Operator turns ("Our next question is from...") are never claim-worthy
    on their own; they live in the next speaker's context_prefix. Asserts
    no Operator turn surfaces as a standalone chunk in the output.
    """
    chunks = chunk_transcript(_read_fixture())
    op_chunks = [c for c in chunks if c.speaker.strip().lower() == "operator"]
    assert op_chunks == [], (
        "Operator turns should be folded into the next speaker's context, "
        f"not emitted standalone. Got {len(op_chunks)}."
    )


def test_paragraph_fallback_when_no_speaker_labels() -> None:
    text = (
        "Apple released its September quarter results today, beating analyst "
        "estimates on both revenue and earnings per share. iPhone revenue "
        "reached a September-quarter record at 46.2 billion dollars.\n\n"
        "Services hit a new all-time high of 24.97 billion dollars, up 12 "
        "percent year over year. The installed base of active devices crossed "
        "an all-time high across every geographic segment.\n\n"
        "Greater China revenue was down 4 percent on a reported basis but "
        "essentially flat on a constant-currency basis."
    )
    assert detect_speaker_turn_format(text) is False
    chunks = chunk_transcript(text, target_chunk_chars=400, overlap_chars=50)
    assert chunks
    for c in chunks:
        assert c.speaker == ""
        assert c.role == ""
        # No Q&A anchor in this snippet → segment is 'unknown'.
        assert c.segment == "unknown"


def test_empty_input_yields_no_chunks() -> None:
    assert chunk_transcript("") == []
    assert chunk_transcript("   \n  \n") == []
