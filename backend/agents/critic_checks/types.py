"""Critic-issue types for the W7/D3 post-writer check layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CriticIssueLevel = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class CriticIssue:
    """One finding from a post-writer schema-driven check.

    ``error``-level issues are blocking — caller should treat them as
    a writer-output rejection (in the same way ValidationError is
    blocking). ``warning``-level surface as critic notes on the
    finished memo. ``info`` is for tooling / introspection only.
    """

    level: CriticIssueLevel
    field: str  # dotted path into the writer payload, e.g. "synergy_estimate.dis_synergies"
    message: str
