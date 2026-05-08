"""UK annual-accounts PDF parser.

Goal: turn a Companies House PDF download into a list of
:class:`FilingSection` records that the existing EDGAR chunker can
consume. Reusing ``core.retrievers.edgar.parser.FilingSection`` keeps
the contract tight — both retrievers feed the same chunker.

Heuristic, not strict, because:

  - PDFs lack the structural markers (HTML tags + ID anchors) that make
    SEC 10-K parsing relatively clean. Section boundaries in UK accounts
    are usually visual (page breaks + bold headings) rather than
    semantic.
  - Format varies a lot. FTSE 100 firms file polished annual reports
    with 100+ pages and rich navigation; small firms file 4-page
    micro-accounts with a single "PROFIT AND LOSS ACCOUNT" line.
  - Auditor and director names sit inside the text, not in metadata.

Strategy:

  1. Extract page-by-page text via PyMuPDF (already in deps).
  2. Walk lines top-to-bottom; when a line matches one of the canonical
     UK-accounts section regexes (Strategic Report, Directors' Report,
     Independent Auditor's Report, Income Statement, Balance Sheet,
     Cash Flow Statement, Notes to the Financial Statements), record
     a section start at that line offset.
  3. Each section's body is everything between its start and the next
     section start (or end of document).
  4. If fewer than 2 canonical sections are found (e.g. micro-account
     PDFs), emit a single ``UNKNOWN`` section containing the whole
     document. The chunker already handles UNKNOWN.

We deliberately do NOT try to parse iXBRL today (Day 4 hard rule). The
financial figures embedded in modern UK annual reports as iXBRL tags
remain present in the text stream — they just get treated as plain
numeric content.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

from core.retrievers.edgar.parser import FilingSection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section taxonomy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _UKSectionSpec:
    item_id: str
    canonical_name: str
    pattern: re.Pattern[str]


def _section_pattern(*alternates: str) -> re.Pattern[str]:
    # Anchor to start-of-line + tolerate optional trailing punctuation /
    # word "for the year ended …" suffix. Headings are usually emitted
    # alone on their own visual line, so we require the line to START
    # with the heading and only allow short trailers.
    body = "|".join(alternates)
    return re.compile(
        rf"^\s*(?:{body})\s*(?:[:\-—–]?[\s\S]{{0,80}})?$",
        re.IGNORECASE | re.MULTILINE,
    )


_UK_SECTIONS: tuple[_UKSectionSpec, ...] = (
    _UKSectionSpec(
        "strategic_report",
        "Strategic Report",
        _section_pattern(r"strategic\s+report"),
    ),
    _UKSectionSpec(
        "directors_report",
        "Directors' Report",
        _section_pattern(r"directors[''']?\s+report", r"report\s+of\s+the\s+directors"),
    ),
    _UKSectionSpec(
        "auditors_report",
        "Independent Auditor's Report",
        _section_pattern(
            r"independent\s+auditor[''']?s?\s+report",
            r"auditor[''']?s?\s+report\s+to\s+the\s+members",
        ),
    ),
    _UKSectionSpec(
        "income_statement",
        "Income Statement",
        _section_pattern(
            r"(?:consolidated\s+)?(?:group\s+)?income\s+statement",
            r"profit\s+and\s+loss\s+account",
            r"(?:consolidated\s+)?statement\s+of\s+(?:comprehensive\s+income|profit\s+or\s+loss)",
        ),
    ),
    _UKSectionSpec(
        "balance_sheet",
        "Balance Sheet",
        _section_pattern(
            r"(?:consolidated\s+)?(?:group\s+)?balance\s+sheet",
            r"(?:consolidated\s+)?statement\s+of\s+financial\s+position",
        ),
    ),
    _UKSectionSpec(
        "cash_flow",
        "Cash Flow Statement",
        _section_pattern(
            r"(?:consolidated\s+)?(?:group\s+)?cash[ -]flow\s+statement",
            r"(?:consolidated\s+)?statement\s+of\s+cash[ -]flows",
        ),
    ),
    _UKSectionSpec(
        "notes",
        "Notes to the Financial Statements",
        _section_pattern(
            r"notes\s+to\s+the\s+(?:consolidated\s+)?financial\s+statements",
            r"notes\s+to\s+the\s+accounts",
        ),
    ),
    _UKSectionSpec(
        "governance",
        "Corporate Governance Report",
        _section_pattern(
            r"corporate\s+governance\s+(?:report|statement)",
            r"governance\s+report",
        ),
    ),
)

_MIN_SECTION_BODY_CHARS: int = 200


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Return the full document text. Each page separated by a single ``\f``.

    PyMuPDF preserves reading order well for ordinary annual reports and
    is fast (the alternative we considered, pypdf, is slower and worse
    on multi-column layouts). Whitespace is normalised lightly — runs
    of spaces collapse to one, but newlines are preserved so the
    section-heading regex can anchor on line starts.
    """
    if not pdf_bytes:
        return ""
    import fitz  # noqa: WPS433  (lazy import — avoid the dependency at import time)

    parts: list[str] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            try:
                txt = page.get_text("text") or ""
            except Exception:  # noqa: BLE001
                logger.exception("PyMuPDF text extraction failed on page %d", i)
                txt = ""
            parts.append(txt)
    joined = "\f".join(parts)
    # Collapse runs of spaces / tabs but preserve newlines.
    joined = re.sub(r"[ \t]+", " ", joined)
    # Drop runs of more than 2 newlines so heading regex matches don't
    # require gymnastics. Form-feed characters from page boundaries are
    # left intact for downstream callers that want page positions.
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined


# ---------------------------------------------------------------------------
# Section walker
# ---------------------------------------------------------------------------


def _find_section_starts(text: str) -> list[tuple[int, _UKSectionSpec]]:
    """Return (offset, spec) for each canonical-section heading we found.

    We collect ALL matches per pattern, then keep the earliest one per
    section (first occurrence is almost always the section heading; later
    occurrences are cross-references like "see Strategic Report on p15").
    Sorted by offset so the caller can slice consecutive sections.
    """
    earliest_per_spec: dict[str, tuple[int, _UKSectionSpec]] = {}
    for spec in _UK_SECTIONS:
        m = spec.pattern.search(text)
        if m and spec.item_id not in earliest_per_spec:
            earliest_per_spec[spec.item_id] = (m.start(), spec)
    starts = list(earliest_per_spec.values())
    starts.sort(key=lambda x: x[0])
    return starts


def parse_pdf(pdf_bytes: bytes) -> list[FilingSection]:
    """Parse a UK annual-accounts PDF into :class:`FilingSection` records.

    Returns ``[]`` only when the PDF is empty or pure-image (no
    extractable text). When >=2 canonical sections are found we emit
    one section per detected heading. Otherwise we emit a single
    ``UNKNOWN`` section containing the whole document (chunker handles).
    """
    text = _extract_pdf_text(pdf_bytes)
    if not text or len(text.strip()) < 100:
        return []

    starts = _find_section_starts(text)
    if len(starts) < 2:
        # Permissive fallback: micro-account or unparseable formatting.
        return [
            FilingSection(
                item_id="UNKNOWN",
                canonical_name="UNKNOWN",
                raw_text=text,
                position_start=0,
                position_end=len(text),
            )
        ]

    sections: list[FilingSection] = []
    for i, (offset, spec) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        body = text[offset:end].strip()
        if len(body) < _MIN_SECTION_BODY_CHARS:
            continue
        sections.append(
            FilingSection(
                item_id=spec.item_id,
                canonical_name=spec.canonical_name,
                raw_text=body,
                position_start=offset,
                position_end=end,
            )
        )
    if not sections:
        # Heading regex matched but every body fell below the floor.
        # Fall back to UNKNOWN so the chunker has something.
        return [
            FilingSection(
                item_id="UNKNOWN",
                canonical_name="UNKNOWN",
                raw_text=text,
                position_start=0,
                position_end=len(text),
            )
        ]
    return sections
