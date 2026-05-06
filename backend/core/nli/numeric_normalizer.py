"""Regex-driven numeric normalizer for the lexical-overlap signal.

Phase 1 / Week 2 / Day 2. The verifier ensemble's third signal is precision-
focused lexical overlap: when a claim asserts a numeric value or a named
entity that does not appear in the cited evidence chunk, that's a real bug
LLM judges (which anchor on gist) tend to miss. This module owns the
numeric half — money, percentages, dates, and bare cardinals.

We do NOT use spaCy for numbers. Its NER is unreliable for currency symbols
across locales (€/£ frequently misclassify, magnitude suffixes get dropped),
and even when it labels something MONEY/PERCENT/CARDINAL it does not give
us a canonical numeric value we can compare with tolerance. Regex-driven
parsing keeps the canonical-value semantics under our control.

Recognised kinds:
    MONEY         currency: "EUR" / "USD" / "GBP"; canonical_value: float
    PERCENT       canonical_value: float in [0, 1] (so "30%" -> 0.30)
    DATE_QUARTER  canonical_value: str like "2024-Q3" or "2025-H1"
    DATE_YEAR     canonical_value: int year
    CARDINAL      canonical_value: float (number with magnitude resolved)

Out of scope this week: every Unicode currency symbol, locale-specific
decimal/thousands separator inversion (we assume comma is thousands and
dot is decimal — the US convention; all the spec test cases use it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NumericValue:
    """A normalised numeric mention.

    Attributes
    ----------
    kind:
        One of "MONEY", "PERCENT", "DATE_QUARTER", "DATE_YEAR", "CARDINAL".
    canonical_value:
        Type depends on kind — see the module docstring.
    raw_text:
        The exact substring of the source text that produced this value.
        Useful for surfacing "claim numerics not in chunk" to the operator.
    currency:
        Three-letter ISO code ("EUR" / "USD" / "GBP") for MONEY only,
        otherwise None.
    span:
        Half-open (start, end) byte/character offsets within the source text.
        The lexical-overlap scorer doesn't read this, but the demo / debug
        tools find it useful.
    """

    kind: str
    canonical_value: Any
    raw_text: str
    currency: str | None = None
    span: tuple[int, int] = (0, 0)


# ---------------------------------------------------------------------------
# Currency + magnitude tables
# ---------------------------------------------------------------------------

# Lower-cased lookup keys → canonical ISO code.
_CURRENCY_NORM: dict[str, str] = {
    "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD",
    "£": "GBP", "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
}

# Lower-cased magnitude suffix → multiplier.
_MAGNITUDE: dict[str, float] = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mn": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "t": 1e12, "trillion": 1e12,
}


def _norm_currency(token: str) -> str | None:
    return _CURRENCY_NORM.get(token.lower())


def _parse_number(num_str: str, magnitude: str | None) -> float:
    """Strip thousands commas, parse, apply magnitude.

    "2,400" -> 2400 (comma = thousands separator).
    "2.4" -> 2.4 (dot = decimal point).
    "2,400.5" -> 2400.5 (US convention).
    """
    cleaned = num_str.replace(",", "")
    val = float(cleaned)
    if magnitude:
        val *= _MAGNITUDE.get(magnitude.lower(), 1.0)
    return val


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Number atom: digits, optional grouped commas, optional decimal.
_NUM_ATOM = r"[\d]+(?:,\d{3})*(?:\.\d+)?|\d+\.\d+"

# Magnitude atom (whole-word for the spelled-out forms; single-letter K/M/B/T
# need to be word-bounded too to avoid eating "Bn" out of "Bnews").
_MAG_ATOM = (
    r"billion|million|thousand|trillion|bn|mn"
    r"|(?:K|k|M|m|B|b|T|t)(?![A-Za-z])"
)

# Currency symbol or three-letter code as a prefix marker.
_CUR_PREFIX_ATOM = r"(?:€|\$|£|\b(?:EUR|USD|GBP)\b)"

# Currency word/code as a suffix marker (after the number).
_CUR_SUFFIX_ATOM = r"(?:euros?|dollars?|pounds?|EUR|USD|GBP)"

RE_MONEY_PREFIX = re.compile(
    rf"({_CUR_PREFIX_ATOM})\s*({_NUM_ATOM})\s*({_MAG_ATOM})?",
    re.IGNORECASE,
)

# Suffix variant: the currency word/code follows the (number, magnitude) pair.
# We require at least one space between the number and the currency word so
# that "EUR" inside "EUR 2.4B" (already prefix-matched) isn't double-counted
# from the trailing direction.
RE_MONEY_SUFFIX = re.compile(
    rf"\b({_NUM_ATOM})\s*({_MAG_ATOM})?\s+({_CUR_SUFFIX_ATOM})\b",
    re.IGNORECASE,
)

RE_PERCENT = re.compile(
    rf"\b({_NUM_ATOM})\s*(?:%|percent\b)",
    re.IGNORECASE,
)

# Quarter / half: Q1..Q4 or H1..H2 followed by a 4-digit year.
RE_DATE_QUARTER = re.compile(
    r"\b(Q[1-4]|H[1-2])\s+(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)

# Standalone 4-digit year. Phase ordering keeps this from matching a year
# that is part of an already-recognised MONEY / PERCENT / DATE_QUARTER span;
# we additionally peek ahead to skip "1990 employees" → CARDINAL.
RE_DATE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")

# CARDINAL — a number that is followed by a lowercase word (the unit/noun).
# Word-boundary on the front so we don't eat the digits out of "$2.4B".
RE_CARDINAL = re.compile(
    rf"\b({_NUM_ATOM})\s*({_MAG_ATOM})?\s+(?=[a-z])",
    re.IGNORECASE,
)


# Cardinal contexts that look like a date when the number is 19xx/20xx but
# the following noun makes it a cardinal count.
_CARDINAL_NOUN_AHEAD_RE = re.compile(
    r"^(employees?|users?|people|companies?|firms?|customers?|workers?|hires?|"
    r"seats?|accounts?|sites?|stores?|deals?|members?|countries|cities|states?|"
    r"products?|orders?|transactions?|partners?|teams?|servers?|machines?|jobs?)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def normalize(text: str) -> list[NumericValue]:
    """Extract every recognised numeric mention from ``text``.

    Phases run in priority order; each phase skips spans already claimed
    by an earlier phase. The output is sorted by source position so the
    lexical-overlap scorer can iterate naturally.
    """
    if not text:
        return []

    matched: list[tuple[int, int]] = []
    out: list[NumericValue] = []

    def _claimed(start: int, end: int) -> bool:
        for s, e in matched:
            if not (end <= s or start >= e):
                return True
        return False

    def _add(nv: NumericValue) -> None:
        out.append(nv)
        matched.append(nv.span)

    # Phase 1a: MONEY with currency-prefix marker.
    for m in RE_MONEY_PREFIX.finditer(text):
        if _claimed(m.start(), m.end()):
            continue
        cur = _norm_currency(m.group(1))
        if not cur:
            continue
        try:
            value = _parse_number(m.group(2), m.group(3))
        except ValueError:
            continue
        _add(
            NumericValue(
                kind="MONEY",
                canonical_value=value,
                raw_text=m.group(0).strip(),
                currency=cur,
                span=(m.start(), m.end()),
            )
        )

    # Phase 1b: MONEY with currency-suffix marker.
    for m in RE_MONEY_SUFFIX.finditer(text):
        if _claimed(m.start(), m.end()):
            continue
        cur = _norm_currency(m.group(3))
        if not cur:
            continue
        try:
            value = _parse_number(m.group(1), m.group(2))
        except ValueError:
            continue
        _add(
            NumericValue(
                kind="MONEY",
                canonical_value=value,
                raw_text=m.group(0).strip(),
                currency=cur,
                span=(m.start(), m.end()),
            )
        )

    # Phase 2: PERCENT.
    for m in RE_PERCENT.finditer(text):
        if _claimed(m.start(), m.end()):
            continue
        try:
            value = float(m.group(1).replace(",", "")) / 100.0
        except ValueError:
            continue
        _add(
            NumericValue(
                kind="PERCENT",
                canonical_value=value,
                raw_text=m.group(0).strip(),
                span=(m.start(), m.end()),
            )
        )

    # Phase 3: DATE_QUARTER.
    for m in RE_DATE_QUARTER.finditer(text):
        if _claimed(m.start(), m.end()):
            continue
        head = m.group(1).upper()
        year = m.group(2)
        canonical = f"{year}-{head}"
        _add(
            NumericValue(
                kind="DATE_QUARTER",
                canonical_value=canonical,
                raw_text=m.group(0).strip(),
                span=(m.start(), m.end()),
            )
        )

    # Phase 4: DATE_YEAR — but skip "1990 employees" style cardinals.
    for m in RE_DATE_YEAR.finditer(text):
        if _claimed(m.start(), m.end()):
            continue
        # Peek the next 30 chars; if they begin with a counted-noun, this
        # is a cardinal-with-year-magnitude-number rather than a year.
        tail = text[m.end() : m.end() + 40].lstrip()
        if _CARDINAL_NOUN_AHEAD_RE.match(tail):
            continue
        _add(
            NumericValue(
                kind="DATE_YEAR",
                canonical_value=int(m.group(1)),
                raw_text=m.group(0),
                span=(m.start(), m.end()),
            )
        )

    # Phase 5: CARDINAL — number directly followed by a lowercase word.
    for m in RE_CARDINAL.finditer(text):
        if _claimed(m.start(), m.end()):
            continue
        try:
            value = _parse_number(m.group(1), m.group(2))
        except ValueError:
            continue
        _add(
            NumericValue(
                kind="CARDINAL",
                canonical_value=value,
                raw_text=m.group(0).strip(),
                span=(m.start(), m.end()),
            )
        )

    out.sort(key=lambda nv: nv.span[0])
    return out


# ---------------------------------------------------------------------------
# Tolerance comparison
# ---------------------------------------------------------------------------

_MONEY_TOLERANCE = 0.02     # ±2% relative
_PERCENT_TOLERANCE = 0.001  # ±0.1pp absolute (0.001 in [0, 1] space)
_CARDINAL_TOLERANCE = 0.05  # ±5% relative; bare counts often drift slightly
                            # in writer-paraphrased text vs source numbers


def values_match(a: NumericValue, b: NumericValue) -> bool:
    """True if ``a`` and ``b`` should be treated as the same fact.

    Tolerances:
        MONEY    same currency AND values within ±2% relative
        PERCENT  values within ±0.001 absolute (0.1 percentage points)
        DATE_*   exact equality (year as int, quarter as canonical string)
        CARDINAL values within ±5% relative

    Different kinds never match. ``MONEY`` of differing currencies never
    match (a € and a £ are different things).
    """
    if a.kind != b.kind:
        return False
    if a.kind == "MONEY":
        if a.currency != b.currency:
            return False
        av = float(a.canonical_value)
        bv = float(b.canonical_value)
        denom = max(abs(av), abs(bv), 1.0)
        return abs(av - bv) / denom <= _MONEY_TOLERANCE
    if a.kind == "PERCENT":
        return abs(float(a.canonical_value) - float(b.canonical_value)) <= _PERCENT_TOLERANCE
    if a.kind in ("DATE_YEAR", "DATE_QUARTER"):
        return a.canonical_value == b.canonical_value
    if a.kind == "CARDINAL":
        av = float(a.canonical_value)
        bv = float(b.canonical_value)
        denom = max(abs(av), abs(bv), 1.0)
        return abs(av - bv) / denom <= _CARDINAL_TOLERANCE
    return False
