"""Pyramid Principle auto-checker — Phase 2 / Week 8 / Day 1.

Two-stage post-writer QA: cheap structural pre-check (deterministic,
no LLM cost) + small-model LLM judge for prose-level structure
(gpt-4o-mini, ~$0.001/call). Findings are advisory — they don't block
``deliverable_ready``.
"""

from .checker import run_pyramid_check  # noqa: F401
from .judge import llm_pyramid_judge  # noqa: F401
from .structural import structural_pyramid_check  # noqa: F401
from .types import PyramidCheckResult, PyramidFinding  # noqa: F401
