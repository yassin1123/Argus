"""MECE list-overlap checker — Phase 2 / Week 8 / Day 2.

Pure-structural framework check: embed each item in an annotated list,
compute pairwise cosine similarity, flag pairs above the threshold.
No LLM judge — pairwise embedding is cheap, deterministic, and the
wedge per the W8/D2 hard rules.

Public surface:
- :func:`run_mece_check` — combined entry point used by the orchestrator.
- :func:`find_mece_check_targets` — Pydantic-introspection walker.
- :func:`check_list_for_overlaps` — similarity engine for one list.
- :class:`MECECheckResult` / :class:`MECEOverlap` — output shape.
"""

from .checker import run_mece_check  # noqa: F401
from .similarity import check_list_for_overlaps  # noqa: F401
from .types import MECECheckResult, MECEOverlap  # noqa: F401
from .walker import find_mece_check_targets  # noqa: F401
