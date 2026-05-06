"""Run-time feature flags read from environment variables.

Currently a single flag — but having a module to expose them avoids
``os.getenv(...)`` calls scattered across the writer/critic/policy code,
keeps the names discoverable, and makes the feature-flag values mockable
in tests via ``monkeypatch.setenv``.

Read-on-import semantics
========================
Flags are read once at module import. Tests that need to flip a flag
should:
1. ``monkeypatch.setenv("ARGUS_USE_ENSEMBLE_VERDICT", "true")``
2. ``import importlib; importlib.reload(core.feature_flags)``

Why not lazy: the writer/critic gates reference the constants as
module attributes, and re-importing per call adds latency to a hot
path that runs per-claim. A reload-on-test pattern keeps prod fast
and tests deterministic.
"""

from __future__ import annotations

import os
from typing import Any


def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# Day 3 — when true, the writer / critic / contradiction-policy gates
# read claim_support_rows.ensemble_verdict instead of the legacy
# verifier_verdict. Default false until Day 5's regression decides.
USE_ENSEMBLE_VERDICT: bool = _truthy("ARGUS_USE_ENSEMBLE_VERDICT")


# Map ensemble verdicts to the legacy verdict vocabulary the
# downstream gates already understand. supported_high / supported_low
# both flow through as "supported"; today the gates do not differentiate
# (per the Day 3 spec hard rule). The split survives in the row's
# ensemble_verdict column for Day 4 regression analysis.
_ENSEMBLE_TO_LEGACY: dict[str, str] = {
    "supported_high": "supported",
    "supported_low": "supported",
    "weak": "weak",
    "unsupported": "unsupported",
    "contradicted": "contradicted",
}


def effective_verdict(row: dict[str, Any]) -> str | None:
    """Return the verdict that downstream gates should use for ``row``.

    With ARGUS_USE_ENSEMBLE_VERDICT off (default): the legacy
    ``verifier_verdict`` column produced by the LLM judge.

    With it on: the ensemble verdict produced by the Day 3 aggregator,
    mapped back to the legacy vocabulary so existing gate code keeps
    working unchanged.

    Re-reads ``USE_ENSEMBLE_VERDICT`` from the module attribute on every
    call so tests can flip the flag via ``importlib.reload`` between
    cases. Hot-path cost is one dict lookup; negligible.
    """
    if USE_ENSEMBLE_VERDICT:
        ev = (row.get("ensemble_verdict") or "").strip().lower()
        mapped = _ENSEMBLE_TO_LEGACY.get(ev)
        if mapped:
            return mapped
        # Ensemble verdict missing (e.g. enrichment skipped on a fallback
        # path) — fall back to the legacy verdict so the gate still has
        # a signal to act on.
    legacy = row.get("verifier_verdict")
    return str(legacy).strip().lower() if legacy else None


__all__ = ["USE_ENSEMBLE_VERDICT", "effective_verdict"]
