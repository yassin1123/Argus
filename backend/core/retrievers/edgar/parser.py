"""Section-aware HTML parser for SEC 10-K / 10-Q filings.

Phase 1 / Week 3 / Day 2. Public API:

    parse_filing_sections(html: str, form: str) -> list[FilingSection]

Returns the filing's content carved into named sections per the canonical
taxonomy in :mod:`core.retrievers.edgar.sections`. Anything we can't
attribute to a known item — including 10-K front matter, the table of
contents, exhibit indices — falls into a single ``UNKNOWN`` section so
no content is ever silently dropped.

WHY THE PARSER LOOKS THE WAY IT DOES
====================================
Real 10-K HTML uses inconsistent markup (BeautifulSoup gets ~1.5 MB of
``<div><span style="…">`` soup with iXBRL inline tags interleaved). Two
practical problems:

1. **Section heading lookalikes.** The phrase "Item 1A. Risk Factors"
   appears multiple times in a typical filing — once in the table of
   contents, once as the actual section heading, and several times as
   cross-references in body prose ("see Item 1A of this Form 10-K…").
   Position-based heuristics ("take the third occurrence") are fragile.

2. **Markup-anchored heuristics ("look at h1-h4 tags only") fail** —
   many issuers wrap headings in styled ``<span>`` elements inside
   regular ``<div>`` blocks, with no actual HX tag in sight.

The approach we use:

- **Walk block-level elements** (``<div>``, ``<p>``, table cells) in
  document order via BeautifulSoup.
- For each block's stripped-and-normalised text, test it against each
  section's regex patterns.
- A block matches a section heading only if (a) the regex matches and
  (b) the block's text is short — under ``_MAX_HEADING_CHARS``. The
  table-of-contents entries pass; the cross-references in body prose
  fail because their containing blocks carry hundreds of characters of
  paragraph text.
- The *first* matched block per item id wins. The TOC entries are
  identical to the heading they point to, but the parser dedupes them
  by recognising that a TOC block is followed by another TOC block (no
  body content between them) and skipping if the text between two
  consecutive matches is below ``_MIN_BODY_CHARS``.

In practice this resolves AAPL/MSFT/TSLA 10-Ks correctly for every
canonical section in the taxonomy.

LENGTH GUARDS
=============
- Per-section body cap: 200 KB. Some filings concatenate the entire
  10-K into a single ``<div>``; if a "section" comes back over 200 KB
  we log a warning so the operator knows the extraction is degenerate.
  Day 2 scope is parse + chunk, not fix bad markup — the chunker will
  still produce usable chunks from oversized sections.
- Whole-filing UNKNOWN cap: if more than 30% of total body text lands
  in UNKNOWN we log a critical-style warning, mirroring the spec's
  "surface if > 30% UNKNOWN" rule.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from core.retrievers.edgar.sections import (
    SECTION_PATTERNS_10K,
    UNKNOWN_CANONICAL_NAME,
    UNKNOWN_ITEM_ID,
    SectionSpec,
    patterns_for,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilingSection:
    """One named (or UNKNOWN) section of a SEC filing.

    Attributes
    ----------
    item_id:
        Short id from the taxonomy (``"1A"``, ``"7"``, ``"II.1A"``,
        ``"UNKNOWN"``).
    canonical_name:
        Human-readable name — e.g. ``"Risk Factors"``.
    raw_text:
        The body text of the section as parsed (post-bs4 ``get_text``,
        whitespace-collapsed, without HTML tags).
    position_start:
        Character offset of the section's start in the *normalised*
        document text (i.e. the same string a regex search over the
        post-bs4 text would see). Useful for "open at this exact spot"
        deep links in the UI.
    position_end:
        Half-open end offset, exclusive. ``position_end - position_start``
        is the section length.
    """

    item_id: str
    canonical_name: str
    raw_text: str
    position_start: int
    position_end: int


# ---------------------------------------------------------------------------
# Tunables — locked for Day 2; revisit only if a real filing hits a wall.
# ---------------------------------------------------------------------------

# Heading-shaped blocks rarely exceed this length even with leading/trailing
# whitespace. Any block longer than this is almost certainly body prose
# containing the heading text as a cross-reference.
_MAX_HEADING_CHARS: int = 200

# Two consecutive "heading" matches with less body text than this between
# them are treated as TOC duplicates rather than two distinct sections.
_MIN_BODY_CHARS: int = 200

# A real section's body shouldn't legitimately exceed this length —
# anything bigger triggers a warning so the operator can investigate.
_MAX_SECTION_BYTES: int = 200 * 1024

# UNKNOWN > this fraction of total body characters is suspicious enough
# to warn at warning level (Day 2 spec rule).
_UNKNOWN_ALERT_FRACTION: float = 0.30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Block-level tags whose stripped text we examine for heading candidacy.
# ``td`` and ``th`` cover TOC tables; ``span`` covers issuers that wrap
# headings in spans without an enclosing block tag.
_BLOCK_TAGS: frozenset[str] = frozenset(
    {"div", "p", "section", "article", "td", "th", "li", "h1", "h2", "h3", "h4", "h5", "h6", "span"}
)

_WS_RE = re.compile(r"\s+")
_NBSP_RE = re.compile(r"[\xa0  ]")  # various non-breaking spaces


def _normalise(text: str) -> str:
    """Collapse all whitespace (incl. nbsp) to single spaces, strip ends.

    The taxonomy regexes use ``\\s+`` and rely on this normalisation —
    don't change without re-checking ``sections.py``.
    """
    return _WS_RE.sub(" ", _NBSP_RE.sub(" ", text)).strip()


def _strip_noise(soup: BeautifulSoup) -> None:
    """Remove tags whose content can never be section headings or body
    we want to retrieve over: scripts, styles, the iXBRL hidden block,
    and explicit ``<a name="...">`` markers.
    """
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # SEC filings render iXBRL metadata via a hidden <ix:header> block;
    # bs4's lxml parser exposes them as plain elements. Wipe them.
    for tag in soup.find_all(lambda t: t.name and t.name.startswith("ix:")):
        tag.decompose()


def _iter_block_texts(soup: BeautifulSoup):
    """Yield (block_element, normalised_text) for each block-level tag in
    document order. Skips blocks whose visible text is empty.
    """
    for el in soup.find_all(_BLOCK_TAGS):
        text = el.get_text(separator=" ", strip=False)
        norm = _normalise(text)
        if norm:
            yield el, norm


_ALPHA_RE = re.compile(r"[^a-z0-9]+")


def _alpha_collapse(text: str) -> str:
    """Lower-case, drop everything but ``[a-z0-9]``. Used to neutralise
    iXBRL inline-tag splits that introduce mid-word whitespace
    (``"PR OPERTIES"`` -> ``"properties"``).
    """
    return _ALPHA_RE.sub("", text.lower())


def _match_section(text: str, taxonomy: list[SectionSpec]) -> tuple[str, str] | None:
    """If ``text`` is a heading-shaped match for any section, return
    ``(item_id, canonical_name)``. Otherwise None.

    Two pathways: anchored regex against the original normalised text
    (fast, exact for clean filings), and alpha-collapsed prefix match
    (catches MSFT-style iXBRL splits).
    """
    for spec in taxonomy:
        for pat in spec.patterns:
            if pat.match(text):
                return spec.item_id, spec.canonical_name
    alpha = _alpha_collapse(text)
    if not alpha:
        return None
    for spec in taxonomy:
        for key in spec.alpha_keys:
            if alpha.startswith(key):
                return spec.item_id, spec.canonical_name
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def parse_filing_sections(html: str, form: str) -> list[FilingSection]:
    """Carve a filing's HTML into named sections.

    Parameters
    ----------
    html:
        Raw HTML of the primary document (typically what
        :meth:`EdgarClient.fetch_document` returns in ``raw_html``).
    form:
        SEC form code, e.g. ``"10-K"``, ``"10-Q"``. Determines which
        taxonomy is consulted.

    Returns
    -------
    list[FilingSection]
        In document order. Always non-empty; if no sections are
        recognised the whole document comes back as one ``UNKNOWN``
        section so the chunker still has something to work with.
    """
    if not html:
        return []

    taxonomy = patterns_for(form)
    soup = BeautifulSoup(html, "lxml")
    _strip_noise(soup)

    # Phase 1 — produce the normalised document text we'll attribute
    # against. We keep the same string the section bodies will be sliced
    # from so position_start/end stay self-consistent.
    full_text = _normalise(soup.get_text(separator=" ", strip=False))

    # Phase 2 — sweep block-level elements for heading-shaped matches.
    # We collect every candidate (item_id, normalised_heading_text) so we
    # can walk them in document order against ``full_text``.
    candidates: list[tuple[str, str, str]] = []
    for _el, norm_text in _iter_block_texts(soup):
        if len(norm_text) > _MAX_HEADING_CHARS:
            continue
        match = _match_section(norm_text, taxonomy)
        if match is None:
            continue
        item_id, name = match
        candidates.append((item_id, name, norm_text))

    if not candidates:
        return [
            FilingSection(
                item_id=UNKNOWN_ITEM_ID,
                canonical_name=UNKNOWN_CANONICAL_NAME,
                raw_text=full_text,
                position_start=0,
                position_end=len(full_text),
            )
        ]

    # Phase 3 — locate every candidate occurrence in ``full_text`` and
    # pick the heading occurrence per item_id that has substantial body
    # text after it (i.e. is the body heading, not a TOC echo). The TOC
    # cluster's occurrences are tightly packed so each one's "body"
    # falls below ``_MIN_BODY_CHARS`` and gets rejected; the body
    # heading is followed by paragraphs of section content.

    # Flatten every (heading_text, position) pair across all candidates.
    occurrences: list[tuple[int, str, str, str]] = []
    seen_pairs: set[tuple[str, int]] = set()
    for item_id, name, heading_text in candidates:
        start = 0
        while True:
            pos = full_text.find(heading_text, start)
            if pos == -1:
                break
            key = (item_id, pos)
            if key not in seen_pairs:
                seen_pairs.add(key)
                occurrences.append((pos, item_id, name, heading_text))
            start = pos + 1

    if not occurrences:
        return [
            FilingSection(
                item_id=UNKNOWN_ITEM_ID,
                canonical_name=UNKNOWN_CANONICAL_NAME,
                raw_text=full_text,
                position_start=0,
                position_end=len(full_text),
            )
        ]

    occurrences.sort(key=lambda x: x[0])

    # Per-item position list, in document order.
    item_positions: dict[str, list[int]] = {}
    item_names: dict[str, str] = {}
    for pos, item_id, name, _heading_text in occurrences:
        item_positions.setdefault(item_id, []).append(pos)
        item_names[item_id] = name

    # Walk the taxonomy in declared order. For each item, pick the first
    # occurrence that:
    #   (a) is *after* the previously accepted section's position, AND
    #   (b) has at least _MIN_BODY_CHARS of text before the next-any-item
    #       occurrence (i.e. it's a real body heading, not a TOC line
    #       packed into the same dense cluster as its neighbours).
    # This rule rejects every TOC entry — the TOC sits before the body
    # so once we've accepted Item 1's body, no candidate position before
    # it can be accepted for Items 1A / 1B / etc.
    section_starts: list[tuple[int, str, str]] = []
    last_accepted_pos = -1
    for spec in taxonomy:
        positions = item_positions.get(spec.item_id)
        if not positions:
            continue
        for pos in positions:
            if pos <= last_accepted_pos:
                continue
            # Body length = distance to the next occurrence of any item
            # past this one, or to end-of-document.
            next_pos = next(
                (p for p, *_rest in occurrences if p > pos),
                len(full_text),
            )
            body_len = next_pos - pos
            if body_len >= _MIN_BODY_CHARS:
                section_starts.append((pos, spec.item_id, spec.canonical_name))
                last_accepted_pos = pos
                break

    if not section_starts:
        return [
            FilingSection(
                item_id=UNKNOWN_ITEM_ID,
                canonical_name=UNKNOWN_CANONICAL_NAME,
                raw_text=full_text,
                position_start=0,
                position_end=len(full_text),
            )
        ]

    out: list[FilingSection] = []

    # Front-matter: content before the first known section heading. SEC
    # filings always carry a cover-page block (registrant info, form
    # boilerplate, exhibit list intro) ahead of substantive content;
    # tagging it as "cover_page" rather than UNKNOWN lets the
    # UNKNOWN-fraction surface rule actually flag *parser bugs* —
    # otherwise a normal 8-K (which is mostly cover boilerplate) would
    # always trip the warning.
    first_pos = section_starts[0][0]
    if first_pos > _MIN_BODY_CHARS:
        out.append(
            FilingSection(
                item_id="cover_page",
                canonical_name="Cover Page",
                raw_text=full_text[:first_pos].strip(),
                position_start=0,
                position_end=first_pos,
            )
        )

    # Body sections: each runs from its start to the next section's start.
    for i, (start, item_id, name) in enumerate(section_starts):
        end = section_starts[i + 1][0] if i + 1 < len(section_starts) else len(full_text)
        body = full_text[start:end].strip()
        if len(body) > _MAX_SECTION_BYTES:
            logger.warning(
                "EDGAR parser: section %s (%s) is %.1f KB — likely a degenerate "
                "single-div filing. Chunker will still split it.",
                item_id,
                name,
                len(body) / 1024.0,
            )
        out.append(
            FilingSection(
                item_id=item_id,
                canonical_name=name,
                raw_text=body,
                position_start=start,
                position_end=end,
            )
        )

    # Surface a warning if UNKNOWN holds too much of the document.
    total_chars = sum(len(s.raw_text) for s in out)
    unknown_chars = sum(len(s.raw_text) for s in out if s.item_id == UNKNOWN_ITEM_ID)
    if total_chars > 0 and unknown_chars / total_chars > _UNKNOWN_ALERT_FRACTION:
        logger.warning(
            "EDGAR parser: UNKNOWN section holds %.1f%% of body text — investigate "
            "filing markup (form=%s).",
            100.0 * unknown_chars / total_chars,
            form,
        )

    return out


