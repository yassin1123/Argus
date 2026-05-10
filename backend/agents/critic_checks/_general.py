"""General-mode post-writer checks. Empty list today — Pydantic
validation already covers the structural contracts the general
schema enforces (non-empty recommendation, source list, etc.). Mode-
specific checks live in their own modules and only fire for that
mode."""

from __future__ import annotations

from typing import Any

from .types import CriticIssue


def check_general(payload: Any) -> list[CriticIssue]:
    """No-op for general-mode payloads today. Reserved for any
    cross-cutting structural checks we want to add later (e.g.
    next_steps must contain at least one time-bound prefix)."""
    return []
