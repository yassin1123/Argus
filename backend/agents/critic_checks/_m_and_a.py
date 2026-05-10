"""M&A-specific post-writer critic checks.

The Pydantic schema (W7/D1) enforces *shape* contracts: every
synergy must carry basis_citations, every valuation point must
declare a methodology, multiples_implied must include EV/EBITDA +
EV/Sales, etc.

These checks enforce *content* contracts the schema can't:

- Valuation must be monotonic (low <= base <= high). A schema can
  require all three values; only this layer can compare them.
- Methodologies across low/base/high must differ. A defensible
  range comes from triangulating DCF + comparable transactions +
  trading comparables; using the same method for all three is a
  single-point estimate dressed up as a range.
- dis-synergies non-empty. Every M&A produces them; an empty list
  is almost always a sign the analyst skipped the work.
- integration_plan first_100_days and first_year non-empty.
- walk_away_triggers must contain at least one digit / percent /
  comparison operator each — a falsifiable threshold, not a
  category.

All checks return WARNING-level by default — they don't reject the
writer's output, they surface for the operator. ERROR escalation is
reserved for cases where shipping the memo would actively mislead.
"""

from __future__ import annotations

import re
from typing import Any

from .types import CriticIssue

_QUANT_RE = re.compile(
    r"\d|%|<\s*=?|>\s*=?|\bover\b|\babove\b|\bbelow\b|\bunder\b|\bat least\b|\bat most\b",
    re.IGNORECASE,
)


def _attr_or_key(obj: Any, name: str) -> Any:
    """Read ``name`` off either a Pydantic-model-shaped object or a
    plain dict. The post-writer dispatcher passes either, so this
    accepts both."""
    if obj is None:
        return None
    if hasattr(obj, name):
        return getattr(obj, name)
    if isinstance(obj, dict):
        return obj.get(name)
    return None


def check_m_and_a(payload: Any) -> list[CriticIssue]:
    issues: list[CriticIssue] = []

    # --- Valuation monotonicity ------------------------------------------
    val = _attr_or_key(payload, "valuation_range")
    if val is not None:
        low = _attr_or_key(_attr_or_key(val, "low"), "gbp_m")
        base = _attr_or_key(_attr_or_key(val, "base"), "gbp_m")
        high = _attr_or_key(_attr_or_key(val, "high"), "gbp_m")
        try:
            l, b, h = float(low), float(base), float(high)
        except (TypeError, ValueError):
            l = b = h = None  # type: ignore[assignment]
        if l is not None and b is not None and h is not None:
            if not (l <= b <= h):
                issues.append(
                    CriticIssue(
                        level="warning",
                        field="valuation_range",
                        message=(
                            f"Valuation not monotonic: low={l}, base={b}, "
                            f"high={h}. Expected low <= base <= high."
                        ),
                    )
                )

        # --- Distinct methodologies across low/base/high -----------------
        m_low = _attr_or_key(_attr_or_key(val, "low"), "methodology")
        m_base = _attr_or_key(_attr_or_key(val, "base"), "methodology")
        m_high = _attr_or_key(_attr_or_key(val, "high"), "methodology")
        methods = [m for m in (m_low, m_base, m_high) if isinstance(m, str) and m.strip()]
        if len(methods) >= 3 and len({m.strip().lower() for m in methods}) == 1:
            issues.append(
                CriticIssue(
                    level="warning",
                    field="valuation_range.methodology",
                    message=(
                        "low / base / high all use the same valuation "
                        "methodology — that's a single-point estimate "
                        "dressed up as a range, not a triangulation."
                    ),
                )
            )

    # --- Dis-synergies non-empty -----------------------------------------
    syn = _attr_or_key(payload, "synergy_estimate")
    if syn is not None:
        dis = _attr_or_key(syn, "dis_synergies") or []
        if not list(dis):
            issues.append(
                CriticIssue(
                    level="warning",
                    field="synergy_estimate.dis_synergies",
                    message=(
                        "dis_synergies list is empty. Every M&A deal "
                        "produces them (customer attrition, talent "
                        "flight, transition cost). Investigate or "
                        "explain why this deal is the exception."
                    ),
                )
            )

    # --- Integration plan non-empty bands --------------------------------
    plan = _attr_or_key(payload, "integration_plan")
    if plan is not None:
        if not list(_attr_or_key(plan, "first_100_days") or []):
            issues.append(
                CriticIssue(
                    level="warning",
                    field="integration_plan.first_100_days",
                    message="first_100_days has no initiative blocks; expected at least one.",
                )
            )
        if not list(_attr_or_key(plan, "first_year") or []):
            issues.append(
                CriticIssue(
                    level="info",
                    field="integration_plan.first_year",
                    message=(
                        "first_year has no initiative blocks. Acceptable "
                        "for very small deals; flagged for review."
                    ),
                )
            )

    # --- Walk-away triggers must be falsifiable --------------------------
    deal = _attr_or_key(payload, "deal_structure_implications")
    if deal is not None:
        triggers = list(_attr_or_key(deal, "walk_away_triggers") or [])
        for i, trig in enumerate(triggers):
            text = str(trig)
            if not _QUANT_RE.search(text):
                issues.append(
                    CriticIssue(
                        level="warning",
                        field=f"deal_structure_implications.walk_away_triggers.{i}",
                        message=(
                            f"Walk-away trigger {text!r} has no quantitative "
                            "threshold (no digit, %, or comparison "
                            "operator). Make it falsifiable: 'top 3 "
                            "customers > 45% at close' beats 'concentration "
                            "risk materialises'."
                        ),
                    )
                )

    return issues
