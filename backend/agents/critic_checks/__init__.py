"""Phase 2 / Week 7 / Day 3 — schema-driven post-writer critic checks.

The ``CriticAgent`` (LLM, runs before the writer) has not been
displaced — it stays. What this package adds is a layer of
deterministic checks that run *after* the writer produces a
structured payload. They look at the actual writer output, not the
analyst's plan, and flag mode-specific contractual gaps that a
plain Pydantic validator can't catch (e.g. monotonic valuation,
distinct methodologies across low/base/high, walk-aways with
quantitative thresholds).

Dispatch mirrors the schema and prompt registries:
``get_mode_checks(mode_name)`` returns the right check function;
unknown modes fall back to the general checks.
"""

from .types import CriticIssue, CriticIssueLevel  # noqa: F401
from ._registry import apply_mode_checks, get_mode_checks  # noqa: F401
