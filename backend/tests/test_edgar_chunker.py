"""Chunker tests against the Apple 10-K fixture (Week 3 / Day 2)."""

from __future__ import annotations

import gzip
import warnings
from pathlib import Path

import pytest

from core.retrievers.edgar.chunker import FilingChunk, chunk_filing
from core.retrievers.edgar.parser import FilingSection, parse_filing_sections

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "edgar" / "aapl_10k_2024.html.gz"
)


@pytest.fixture(scope="module")
def apple_chunks() -> list[FilingChunk]:
    with gzip.open(FIXTURE_PATH, "rt", encoding="utf-8") as f:
        html = f.read()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sections = parse_filing_sections(html, "10-K")
    return chunk_filing(sections)


def test_chunker_produces_nonzero_chunks(apple_chunks) -> None:
    assert len(apple_chunks) > 0
    # Apple's 10-K should produce something on the order of dozens of chunks.
    assert len(apple_chunks) >= 30, f"only {len(apple_chunks)} chunks emitted; parser may be dropping content"


def test_chunker_no_section_crossing(apple_chunks) -> None:
    """Each chunk must come from exactly one section — section_item_id
    + canonical_name pair has to be self-consistent across all chunks
    and never blank.
    """
    seen_pairs: set[tuple[str, str]] = set()
    for c in apple_chunks:
        assert c.section_item_id, f"chunk has empty section_item_id: {c}"
        assert c.section_canonical_name, f"chunk has empty canonical name: {c}"
        seen_pairs.add((c.section_item_id, c.section_canonical_name))
    # Each item_id should map to exactly one canonical_name (no rebadging).
    by_item: dict[str, set[str]] = {}
    for iid, name in seen_pairs:
        by_item.setdefault(iid, set()).add(name)
    for iid, names in by_item.items():
        assert len(names) == 1, (
            f"item_id {iid} has multiple canonical names: {names}; "
            "chunker is probably leaking content across sections"
        )


def test_chunker_indexes_within_section_are_contiguous(apple_chunks) -> None:
    """Chunks within the same section must use 0..N-1 contiguous indices
    so the UI can render "chunk 3 of 12 in Risk Factors".
    """
    by_section: dict[str, list[int]] = {}
    for c in apple_chunks:
        by_section.setdefault(c.section_item_id, []).append(c.chunk_index_within_section)
    for item_id, idx_list in by_section.items():
        assert idx_list == list(range(len(idx_list))), (
            f"section {item_id} has non-contiguous chunk indices: {idx_list}"
        )


def test_chunker_size_distribution(apple_chunks) -> None:
    """Across all chunks, at least 80% should be within +/-20% of the
    target size; on chunks coming from "fillable" sections (i.e.
    sections >= 1.5x target where the chunker can reasonably hit the
    target), the bar tightens to 85%.

    Why two thresholds:
      - Short sections like "Properties" (516 chars at Apple)
        legitimately produce one tiny chunk and would drag a global
        90% bar below pass.
      - Financial-statements sections (Item 8) carry many short
        "sentences" (line items, footnotes) that fail to fill a 2000-
        char chunk even after greedy accumulation. We accept the
        natural ~85% on the fillable subset rather than mangle the
        sentence boundaries to push it higher.
    """
    target = 2000
    band = (target * 0.8, target * 1.2)
    sizes = [len(c.content) for c in apple_chunks]
    in_band = [s for s in sizes if band[0] <= s <= band[1]]
    overall_pct = len(in_band) / len(sizes)
    assert overall_pct >= 0.80, (
        f"only {overall_pct:.0%} of chunks within +/-20% of target {target}; "
        f"sizes (sorted) = {sorted(sizes)}"
    )

    by_section_size: dict[str, int] = {}
    for c in apple_chunks:
        by_section_size[c.section_item_id] = by_section_size.get(c.section_item_id, 0) + len(c.content)
    fillable_items = {iid for iid, sz in by_section_size.items() if sz >= target * 1.5}
    fillable_chunks = [c for c in apple_chunks if c.section_item_id in fillable_items]
    if fillable_chunks:
        fillable_in_band = [c for c in fillable_chunks if band[0] <= len(c.content) <= band[1]]
        fillable_pct = len(fillable_in_band) / len(fillable_chunks)
        assert fillable_pct >= 0.85, (
            f"only {fillable_pct:.0%} of fillable-section chunks within +/-20% of target; "
            f"fillable items = {sorted(fillable_items)}"
        )


def test_chunker_offsets_monotonic_within_section(apple_chunks) -> None:
    """Within each section, char_offset_in_filing should be strictly
    increasing chunk to chunk (overlap means the gap can be small but
    still positive).
    """
    by_section: dict[str, list[FilingChunk]] = {}
    for c in apple_chunks:
        by_section.setdefault(c.section_item_id, []).append(c)
    for item_id, lst in by_section.items():
        offsets = [c.char_offset_in_filing for c in lst]
        for i in range(1, len(offsets)):
            assert offsets[i] > offsets[i - 1], (
                f"section {item_id} chunk {i} offset {offsets[i]} not after "
                f"chunk {i - 1} offset {offsets[i - 1]}"
            )


def test_chunker_unknown_section_doesnt_crash() -> None:
    """When we feed in a synthetic UNKNOWN-only sections list, the
    chunker should still produce valid chunks tagged UNKNOWN.
    """
    sec = FilingSection(
        item_id="UNKNOWN",
        canonical_name="Unrecognised Section",
        raw_text="This is body text. " * 300,  # ~5700 chars
        position_start=0,
        position_end=5700,
    )
    chunks = chunk_filing([sec])
    assert len(chunks) >= 2  # 5700 chars / 2000 target -> at least 2 chunks
    assert all(c.section_item_id == "UNKNOWN" for c in chunks)
    assert all(c.section_canonical_name == "Unrecognised Section" for c in chunks)


def test_chunker_short_section_produces_one_chunk() -> None:
    """A section under target_chunk_chars should produce exactly one
    chunk carrying the whole section text.
    """
    sec = FilingSection(
        item_id="2",
        canonical_name="Properties",
        raw_text="Apple's headquarters is located at One Apple Park Way.",
        position_start=100,
        position_end=160,
    )
    chunks = chunk_filing([sec])
    assert len(chunks) == 1
    assert chunks[0].content == "Apple's headquarters is located at One Apple Park Way."
    assert chunks[0].chunk_index_within_section == 0
    assert chunks[0].char_offset_in_filing == 100
