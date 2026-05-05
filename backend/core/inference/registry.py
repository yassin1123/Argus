"""Logical task kinds for routing and usage (stable string keys)."""

from __future__ import annotations

from enum import Enum


class TaskKind(str, Enum):
    PLANNER = "planner"
    RESEARCHER = "researcher"
    RESEARCH_SUBAGENT = "research_subagent"
    ANALYST = "analyst"
    CRITIC = "critic"
    VERIFIER = "verifier"
    WRITER = "writer"
    ENTAILMENT = "entailment"
