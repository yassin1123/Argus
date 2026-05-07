"""Section-aware parser tests against a real Apple 10-K (Week 3 / Day 2).

The fixture (~100KB gzipped) is checked in so CI can exercise the
parser without ever hitting sec.gov.
"""

from __future__ import annotations

import gzip
import warnings
from pathlib import Path

import pytest

from core.retrievers.edgar.parser import _MAX_SECTION_BYTES, parse_filing_sections
from core.retrievers.edgar.sections import UNKNOWN_ITEM_ID

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "edgar" / "aapl_10k_2024.html.gz"


def _load_apple_10k() -> str:
    with gzip.open(FIXTURE_PATH, "rt", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def apple_10k_html() -> str:
    return _load_apple_10k()


@pytest.fixture(scope="module")
def apple_sections(apple_10k_html: str):
    # bs4's lxml parser logs an XMLParsedAsHTMLWarning on iXBRL filings;
    # silence it just for these tests so failure output stays readable.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return parse_filing_sections(apple_10k_html, "10-K")


def test_parse_apple_10k_finds_canonical_sections(apple_sections) -> None:
    """At least 8 of the canonical 10-K sections should be located by
    name in Apple's filing. Apple's actual 10-K covers Items 1, 1A, 2,
    3, 5, 7, 7A, 8, 9A, 9B in body — the parser should find all of them.
    """
    found_ids = {s.item_id for s in apple_sections if s.item_id != UNKNOWN_ITEM_ID}
    expected_min = {"1", "1A", "2", "3", "5", "7", "7A", "8"}
    assert expected_min.issubset(found_ids), (
        f"missing canonical sections: expected superset of {expected_min}, "
        f"got {found_ids}"
    )
    assert len(found_ids) >= 8, (
        f"parser should find at least 8 named sections in Apple's 10-K, "
        f"got {len(found_ids)}: {sorted(found_ids)}"
    )


def test_parse_apple_10k_unknown_under_30pct(apple_sections) -> None:
    """If more than 30% of body text falls into UNKNOWN, the parser is
    failing to recognise canonical sections — surface as a parser bug
    not an edge case (per Day 2 spec hard rule).
    """
    total = sum(len(s.raw_text) for s in apple_sections)
    unknown_chars = sum(
        len(s.raw_text) for s in apple_sections if s.item_id == UNKNOWN_ITEM_ID
    )
    assert total > 0
    fraction = unknown_chars / total
    assert fraction <= 0.30, (
        f"UNKNOWN holds {fraction:.1%} of body text; investigate the parser. "
        f"sections: {[(s.item_id, len(s.raw_text)) for s in apple_sections]}"
    )


def test_parse_apple_10k_section_positions_monotonic(apple_sections) -> None:
    """Sections must come back in document order — sanity-check on
    the parser's position bookkeeping.
    """
    starts = [s.position_start for s in apple_sections]
    assert starts == sorted(starts), (
        f"sections out of document order: {[(s.item_id, s.position_start) for s in apple_sections]}"
    )
    # And section bodies shouldn't overlap.
    for i in range(len(apple_sections) - 1):
        assert apple_sections[i].position_end <= apple_sections[i + 1].position_start


def test_parse_apple_10k_no_section_over_size_cap(apple_sections, caplog) -> None:
    """No section should exceed the soft 200KB cap. If one does, the
    parser logs a warning — captured here so a regression that puts the
    whole filing into one section is loudly surfaced.
    """
    oversized = [s for s in apple_sections if len(s.raw_text) > _MAX_SECTION_BYTES]
    assert not oversized, (
        f"oversized section(s) found: {[(s.item_id, len(s.raw_text)) for s in oversized]}"
    )


def test_unknown_section_handling_on_malformed_html() -> None:
    """When parser can't find any section, it returns ONE UNKNOWN bucket
    carrying all body text — never raises, never silently drops content.
    """
    malformed = "<html><body><p>This filing has no recognisable section headings whatsoever.</p></body></html>"
    sections = parse_filing_sections(malformed, "10-K")
    assert len(sections) == 1
    assert sections[0].item_id == UNKNOWN_ITEM_ID
    assert "no recognisable section headings" in sections[0].raw_text


def test_empty_html_returns_empty_list() -> None:
    assert parse_filing_sections("", "10-K") == []
    assert parse_filing_sections(None, "10-K") == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Coverage for 8-K / DEF 14A / S-1 (Week 3 / Day 3 — new form taxonomies).
#
# The fixtures are real SEC filings downloaded by the operator and
# committed gzipped under backend/tests/fixtures/edgar/. The bar is:
#
#   - non-empty section list
#   - UNKNOWN under 30% (cover_page is its own bucket and isn't counted)
#   - at least N canonical sections recognised — N depends on the form
#
# AAPL's 8-Ks are minimal (cover + 1-2 items + exhibit list); we don't
# require every taxonomy entry to land. Same for the DEF 14A; some
# issuers skip the audit-committee subsection.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def aapl_8k_sections():
    path = Path(__file__).resolve().parent / "fixtures" / "edgar" / "aapl_8k.html.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        html = f.read()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return parse_filing_sections(html, "8-K")


@pytest.fixture(scope="module")
def aapl_def14a_sections():
    path = Path(__file__).resolve().parent / "fixtures" / "edgar" / "aapl_def14a.html.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        html = f.read()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return parse_filing_sections(html, "DEF 14A")


@pytest.fixture(scope="module")
def rddt_s1_sections():
    path = Path(__file__).resolve().parent / "fixtures" / "edgar" / "rddt_s1.html.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        html = f.read()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return parse_filing_sections(html, "S-1")


def _unknown_fraction(sections) -> float:
    total = sum(len(s.raw_text) for s in sections) or 1
    unk = sum(len(s.raw_text) for s in sections if s.item_id == UNKNOWN_ITEM_ID)
    return unk / total


def test_parse_8k_finds_canonical_items(aapl_8k_sections) -> None:
    found = {s.item_id for s in aapl_8k_sections if s.item_id != UNKNOWN_ITEM_ID}
    # AAPL's earnings 8-Ks always carry these two.
    assert "2.02" in found, f"missing item 2.02; got {found}"
    assert "9.01" in found, f"missing item 9.01; got {found}"
    assert _unknown_fraction(aapl_8k_sections) <= 0.30


def test_parse_def14a_finds_canonical_sections(aapl_def14a_sections) -> None:
    found = {s.item_id for s in aapl_def14a_sections if s.item_id != UNKNOWN_ITEM_ID}
    # Every Apple proxy carries these.
    expected = {"election", "governance", "compensation_discussion"}
    assert expected.issubset(found), f"missing canonical DEF 14A sections; got {found}"
    assert _unknown_fraction(aapl_def14a_sections) <= 0.30


def test_parse_s1_finds_canonical_sections(rddt_s1_sections) -> None:
    found = {s.item_id for s in rddt_s1_sections if s.item_id != UNKNOWN_ITEM_ID}
    # An IPO S-1 must carry summary, risk factors, MD&A, business,
    # management, financial statements at minimum.
    expected = {"summary", "risk_factors", "mda", "business", "management", "financial_statements"}
    assert expected.issubset(found), f"missing canonical S-1 sections; got {found}"
    assert _unknown_fraction(rddt_s1_sections) <= 0.30
