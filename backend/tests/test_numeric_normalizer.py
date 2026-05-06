"""Numeric normalizer fixture (Week 2 / Day 2).

Each case is (input_text, expected_kind, expected_currency, expected_value).
The normalizer may produce more than one value if the text contains other
recognised mentions; the assertion is that at least one matched value
satisfies the expected (kind, currency, canonical_value) triple within the
declared tolerance.
"""

from __future__ import annotations

import pytest

from core.nli.numeric_normalizer import NumericValue, normalize, values_match


# Helper: synthesise an "expected" NumericValue and check that normalize()
# returned at least one match for it under the standard tolerance.
def _has_match(values: list[NumericValue], expected: NumericValue) -> bool:
    return any(values_match(v, expected) for v in values)


def _expect(kind: str, value: object, *, currency: str | None = None) -> NumericValue:
    return NumericValue(kind=kind, canonical_value=value, raw_text="<expected>", currency=currency)


# ---------------------------------------------------------------------------
# Currency variants — EUR (7 inputs, all -> 2.4e9 EUR)
# ---------------------------------------------------------------------------

EUR_2_4B_INPUTS = [
    "€2.4B",
    "€2.4 billion",
    "EUR 2.4B",
    "2.4 billion euros",
    "€2,400M",
    "€2,400 million",
    "€2.4bn",
]


@pytest.mark.parametrize("text", EUR_2_4B_INPUTS)
def test_money_eur_2_4_billion(text: str) -> None:
    expected = _expect("MONEY", 2_400_000_000.0, currency="EUR")
    out = normalize(text)
    assert _has_match(out, expected), (
        f"normalize({text!r}) -> {out!r}; expected a (MONEY, EUR, 2.4e9) match"
    )


# ---------------------------------------------------------------------------
# USD (4 inputs)
# ---------------------------------------------------------------------------

USD_2_4B_INPUTS = [
    "$2.4B",
    "$2.4 billion",
    "USD 2.4B",
    "2.4 billion dollars",
]


@pytest.mark.parametrize("text", USD_2_4B_INPUTS)
def test_money_usd_2_4_billion(text: str) -> None:
    expected = _expect("MONEY", 2_400_000_000.0, currency="USD")
    out = normalize(text)
    assert _has_match(out, expected), (
        f"normalize({text!r}) -> {out!r}; expected a (MONEY, USD, 2.4e9) match"
    )


# ---------------------------------------------------------------------------
# GBP (4 inputs)
# ---------------------------------------------------------------------------

GBP_500K_INPUTS = [
    "£500K",
    "£500,000",
    "500 thousand pounds",
    "GBP 500K",
]


@pytest.mark.parametrize("text", GBP_500K_INPUTS)
def test_money_gbp_500k(text: str) -> None:
    expected = _expect("MONEY", 500_000.0, currency="GBP")
    out = normalize(text)
    assert _has_match(out, expected), (
        f"normalize({text!r}) -> {out!r}; expected a (MONEY, GBP, 500_000) match"
    )


# ---------------------------------------------------------------------------
# Percentages (4 inputs)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected_value"),
    [
        ("30%", 0.30),
        ("30 percent", 0.30),
        ("30.5%", 0.305),
        ("0.5%", 0.005),
    ],
)
def test_percent(text: str, expected_value: float) -> None:
    expected = _expect("PERCENT", expected_value)
    out = normalize(text)
    assert _has_match(out, expected), (
        f"normalize({text!r}) -> {out!r}; expected (PERCENT, {expected_value})"
    )


# ---------------------------------------------------------------------------
# Dates (4 inputs)
# ---------------------------------------------------------------------------

def test_date_year_bare_2024() -> None:
    out = normalize("In 2024 the company expanded.")
    expected = _expect("DATE_YEAR", 2024)
    assert _has_match(out, expected), f"normalize -> {out!r}"


def test_date_quarter_q3_2024() -> None:
    out = normalize("Revenue peaked in Q3 2024.")
    expected = _expect("DATE_QUARTER", "2024-Q3")
    assert _has_match(out, expected), f"normalize -> {out!r}"


def test_date_quarter_q4_2023() -> None:
    out = normalize("Q4 2023 was the best quarter.")
    expected = _expect("DATE_QUARTER", "2023-Q4")
    assert _has_match(out, expected), f"normalize -> {out!r}"


def test_date_quarter_h1_2025() -> None:
    out = normalize("Targeting launch in H1 2025.")
    expected = _expect("DATE_QUARTER", "2025-H1")
    assert _has_match(out, expected), f"normalize -> {out!r}"


# ---------------------------------------------------------------------------
# Cardinals (3 inputs)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected_value"),
    [
        ("12 employees", 12.0),
        ("50 people", 50.0),
        ("1.5 million users", 1_500_000.0),
    ],
)
def test_cardinal(text: str, expected_value: float) -> None:
    expected = _expect("CARDINAL", expected_value)
    out = normalize(text)
    assert _has_match(out, expected), (
        f"normalize({text!r}) -> {out!r}; expected (CARDINAL, {expected_value})"
    )


# ---------------------------------------------------------------------------
# Tolerance behaviour
# ---------------------------------------------------------------------------

def test_money_tolerance_within_band() -> None:
    """€2.4B vs €2.42B is ~0.83% apart — must match under the ±2% tolerance."""
    a = _expect("MONEY", 2.4e9, currency="EUR")
    b = _expect("MONEY", 2.42e9, currency="EUR")
    assert values_match(a, b)


def test_money_tolerance_out_of_band() -> None:
    """€2.4B vs €2.5B is ~4.2% apart — must NOT match (tolerance is ±2%)."""
    a = _expect("MONEY", 2.4e9, currency="EUR")
    b = _expect("MONEY", 2.5e9, currency="EUR")
    assert not values_match(a, b)


def test_money_different_currency_never_matches() -> None:
    eur = _expect("MONEY", 1.0e9, currency="EUR")
    usd = _expect("MONEY", 1.0e9, currency="USD")
    assert not values_match(eur, usd)


def test_percent_tolerance_within_band() -> None:
    """30% vs 30.05% is 0.05pp apart — under the ±0.1pp tolerance."""
    a = _expect("PERCENT", 0.30)
    b = _expect("PERCENT", 0.3005)
    assert values_match(a, b)


def test_percent_tolerance_out_of_band() -> None:
    """30% vs 30.5% is 0.5pp apart — over the ±0.1pp tolerance."""
    a = _expect("PERCENT", 0.30)
    b = _expect("PERCENT", 0.305)
    assert not values_match(a, b)


def test_date_year_exact_only() -> None:
    assert values_match(_expect("DATE_YEAR", 2024), _expect("DATE_YEAR", 2024))
    assert not values_match(_expect("DATE_YEAR", 2024), _expect("DATE_YEAR", 2025))


def test_date_quarter_exact_only() -> None:
    assert values_match(_expect("DATE_QUARTER", "2024-Q3"), _expect("DATE_QUARTER", "2024-Q3"))
    assert not values_match(_expect("DATE_QUARTER", "2024-Q3"), _expect("DATE_QUARTER", "2024-Q4"))


# ---------------------------------------------------------------------------
# Disambiguation
# ---------------------------------------------------------------------------

def test_year_followed_by_employees_is_cardinal_not_year() -> None:
    """\"1990 employees\" should be CARDINAL=1990, not DATE_YEAR=1990."""
    out = normalize("They have 1990 employees on payroll.")
    kinds = {nv.kind for nv in out}
    assert "CARDINAL" in kinds
    assert "DATE_YEAR" not in kinds


def test_money_takes_priority_over_cardinal() -> None:
    """\"2.4 billion users\" is CARDINAL; \"$2.4 billion\" is MONEY. The
    presence of a currency cue must promote the same number to MONEY.
    """
    cardinal_only = normalize("They have 2.4 billion users.")
    money_present = normalize("They earned $2.4 billion last year.")
    assert any(nv.kind == "CARDINAL" for nv in cardinal_only)
    assert any(nv.kind == "MONEY" and nv.currency == "USD" for nv in money_present)


def test_multiple_values_in_one_string() -> None:
    """Realistic mixed string — every component must be picked up."""
    text = (
        "In Q3 2024 the company grew revenue 30% to €2.4B with 12 employees, "
        "vs Q3 2023 when it was below €1B."
    )
    out = normalize(text)

    assert _has_match(out, _expect("DATE_QUARTER", "2024-Q3"))
    assert _has_match(out, _expect("DATE_QUARTER", "2023-Q3"))
    assert _has_match(out, _expect("PERCENT", 0.30))
    assert _has_match(out, _expect("MONEY", 2.4e9, currency="EUR"))
    assert _has_match(out, _expect("MONEY", 1.0e9, currency="EUR"))
    assert _has_match(out, _expect("CARDINAL", 12.0))
