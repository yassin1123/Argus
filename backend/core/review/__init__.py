"""Engagement-review module — Phase 4 / Week 15.

Public surface:

  - :class:`ReviewState` / :class:`ReviewAction` / :func:`apply_transition`
    / :func:`can_transition` / :func:`legal_actions` — the state
    machine (W15/D1).
  - :class:`AuthorizationResult` / :func:`authorize_action` — role +
    actor + self-approval gating (W15/D1).
  - :func:`is_locked` / :func:`should_auto_revert_on_edit` — lock
    semantics for terminal review states (W15/D1).
"""

from .authorization import AuthorizationResult, authorize_action
from .locking import is_locked, should_auto_revert_on_edit
from .state_machine import (
    ReviewAction,
    ReviewState,
    TransitionResult,
    apply_transition,
    can_transition,
    legal_actions,
    next_state,
)

__all__ = [
    "AuthorizationResult",
    "ReviewAction",
    "ReviewState",
    "TransitionResult",
    "apply_transition",
    "authorize_action",
    "can_transition",
    "is_locked",
    "legal_actions",
    "next_state",
    "should_auto_revert_on_edit",
]
