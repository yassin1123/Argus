"""Mode → critic-checks registry.

Mirrors the schema and prompt registries: mode slug -> check function.
Built-in modes share ``check_general`` (a no-op today) until they get
bespoke checks. ``m_and_a_diligence`` ships with the strict M&A
content checks.
"""

from __future__ import annotations

from typing import Any, Callable

from .types import CriticIssue
from ._general import check_general
from ._m_and_a import check_m_and_a

# Mode slug -> function(payload) -> list[CriticIssue]
ChecksFn = Callable[[Any], list[CriticIssue]]

_CHECKS_REGISTRY: dict[str, ChecksFn] = {
    "general": check_general,
    "market_entry": check_general,
    "due_diligence": check_general,
    "growth_strategy": check_general,
    "m_and_a_diligence": check_m_and_a,
}


def get_mode_checks(mode_name: str) -> ChecksFn:
    """Return the post-writer check function for ``mode_name``. Falls
    back to :func:`check_general` for unknown / firm-defined slugs."""
    return _CHECKS_REGISTRY.get(mode_name, check_general)


def apply_mode_checks(mode_name: str, payload: Any) -> list[CriticIssue]:
    """Run the registered checks for ``mode_name`` against ``payload``
    and return any issues found. Always returns a list (possibly
    empty)."""
    return list(get_mode_checks(mode_name)(payload))
