"""Explicit pipeline states for session lifecycle (auditable transitions)."""

from typing import Literal

PipelineState = Literal[
    "idle",
    "plan_ready",
    "research_gathered",
    "analysis_v1_done",
    "critique_done",
    "analysis_v2_done",
    "gates_validated",
    "critic_post_done",
    "verification_done",
    "deliverable_ready",
    "evidence_insufficient",
    "failed",
]

VALID_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "idle": ("plan_ready",),
    "plan_ready": ("research_gathered", "failed", "evidence_insufficient"),
    "research_gathered": ("analysis_v1_done", "failed", "evidence_insufficient"),
    "analysis_v1_done": ("critique_done", "failed"),
    "critique_done": ("analysis_v2_done", "failed"),
    "analysis_v2_done": ("gates_validated", "evidence_insufficient", "failed"),
    "gates_validated": ("critic_post_done", "failed"),
    "critic_post_done": ("verification_done", "analysis_v2_done", "failed"),
    "verification_done": ("deliverable_ready", "evidence_insufficient", "failed"),
    "deliverable_ready": tuple(),
    "evidence_insufficient": tuple(),
    "failed": tuple(),
}


def can_transition(from_state: str, to_state: str) -> bool:
    allowed = VALID_TRANSITIONS.get(from_state, tuple())
    return to_state in allowed
