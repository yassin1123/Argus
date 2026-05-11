"""Mode → critic-checks registry.

Mirrors the schema and prompt registries: mode slug -> check function.
Built-in modes share ``check_general`` (a no-op today) until they get
bespoke checks. ``m_and_a_diligence`` ships with the strict M&A
content checks.

W8/D4 adds a cross-mode :func:`check_required_frameworks` pass that
runs in addition to the mode-name-routed check, driven by the
resolved mode's ``frameworks`` config. It fires for every mode that
declares required frameworks (M&A, growth_strategy today); modes
without a declaration produce no findings.
"""

from __future__ import annotations

from typing import Any, Callable, TYPE_CHECKING

from .types import CriticIssue
from ._frameworks import check_required_frameworks
from ._general import check_general
from ._m_and_a import check_m_and_a

if TYPE_CHECKING:
    from core.consulting_modes import ResolvedConsultingMode  # noqa: F401

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


def apply_mode_checks(
    mode_name: str,
    payload: Any,
    *,
    resolved_mode: "ResolvedConsultingMode | None" = None,
) -> list[CriticIssue]:
    """Run the registered checks for ``mode_name`` against ``payload``
    and return any issues found. Always returns a list (possibly
    empty).

    W8/D4: when ``resolved_mode`` is supplied, the
    :func:`check_required_frameworks` cross-mode check also runs and
    its findings are appended. Older callers that omit ``resolved_mode``
    keep their pre-W8 behaviour (mode-name-routed checks only).
    """
    issues: list[CriticIssue] = list(get_mode_checks(mode_name)(payload))
    if resolved_mode is not None:
        fw_cfg = getattr(resolved_mode, "frameworks", None)
        issues.extend(check_required_frameworks(payload, fw_cfg))
    return issues
