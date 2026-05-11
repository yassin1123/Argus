"""Consulting-mode loading.

Two surfaces:

* **Legacy** (`load_modes`, `get_mode_config`, `check_mode_satisfied`,
  `branch_ids_from_evidence_claims`) — the flat-YAML API every existing
  caller uses today. Unchanged behaviour.

* **Layered resolver** (`resolve_mode`, `load_mode_legacy`,
  `ResolvedConsultingMode`) — Phase 2 / Week 6 / Day 1. Resolves
  built-in YAML <- firm_modes <- engagement_mode_overrides. New callers
  (planner / writer / verifier in Day 4 work) thread firm_id and
  engagement_id through `resolve_mode`.
"""

from core._consulting_modes_legacy import (  # noqa: F401 — re-export
    branch_ids_from_evidence_claims,
    check_mode_satisfied,
    get_mode_config,
    load_modes,
)

from .resolver import (  # noqa: F401 — re-export
    CACHE_TTL_SECONDS,
    OVERLAY_MAX_CHARS,
    apply_trust_rules,
    check_resolved_mode_satisfied,
    invalidate_engagement,
    invalidate_firm_mode,
    load_mode_legacy,
    resolve_mode,
)
from .types import (  # noqa: F401 — re-export
    FrameworksModeConfig,
    ModeConfigError,
    ModeNotFoundError,
    ResolvedConsultingMode,
)
