"""Engagement-review state machine — Phase 4 / Week 15 / Day 1.

Pure logic. No DB calls; no API surface. The W15/D2 work wires this
into the persistence layer; the W15/D3 work wires the API endpoints
that drive it.

Two enums + a transition table:

  - :class:`ReviewState` — the five lifecycle states an engagement
    moves through (``draft → in_review → changes_requested →
    approved → delivered``). Stored on ``sessions.review_state``
    (column added in migration 036).
  - :class:`ReviewAction` — the seven user-driven (plus one
    system-driven, ``auto_revert``) actions that drive transitions.
    Each action maps to exactly one ``(from, to)`` pair so the
    state machine is unambiguous.
  - :data:`_TRANSITIONS` — the validity table. Anything not in this
    table is rejected by :func:`can_transition`.

Hard rules baked into the state machine:

  - **No direct ``draft → approved`` skip.** A submit_for_review
    leg is mandatory.
  - **No transitions back into ``in_review`` from a terminal-ish
    state without going through ``draft`` first.** ``reopen`` lands
    on ``draft`` so the engagement explicitly re-enters the
    lifecycle from the top.
  - **Idempotent transitions** (``approve`` on an already-approved
    session, etc.) are NOT free passes — they return False from
    :func:`can_transition`. Callers MUST inspect the current state
    before acting.

The role / actor / self-approval policy lives in
``core/review/authorization.py``; the lock semantics for
post-approval edits live in ``core/review/locking.py``. This module
stays focused on "which transitions are structurally legal".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReviewState(str, Enum):
    """Lifecycle state of an engagement's review.

    ``str`` mixin so the values double as DB-friendly strings —
    e.g. ``ReviewState.DRAFT == "draft"`` is true, and the enum
    serialises into the ``sessions.review_state`` column without
    a conversion step.
    """

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    DELIVERED = "delivered"


class ReviewAction(str, Enum):
    """The set of actions that can drive a transition. The first six
    are user-driven; ``AUTO_REVERT`` is system-driven (W15/D2 fires
    it when an approved/delivered engagement is edited)."""

    SUBMIT_FOR_REVIEW = "submit_for_review"
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    RESUBMIT = "resubmit"
    MARK_DELIVERED = "mark_delivered"
    REOPEN = "reopen"
    AUTO_REVERT = "auto_revert"


# Transition table: {from_state: {action: to_state}}.
# Anything not in this table is rejected. Order:
#
#   DRAFT             --submit_for_review--> IN_REVIEW
#   IN_REVIEW         --approve-----------> APPROVED
#   IN_REVIEW         --request_changes---> CHANGES_REQUESTED
#   CHANGES_REQUESTED --resubmit----------> IN_REVIEW
#   APPROVED          --mark_delivered----> DELIVERED
#   APPROVED          --reopen------------> DRAFT
#   APPROVED          --auto_revert-------> DRAFT  (W15/D2 edit-trigger)
#   DELIVERED         --reopen------------> DRAFT  (admin-only escape hatch)
#   DELIVERED         --auto_revert-------> DRAFT  (same edit-trigger path
#                                                   in case a delivered
#                                                   engagement is touched
#                                                   post-hoc; rare but
#                                                   we treat it the same
#                                                   way as approved.)
_TRANSITIONS: dict[ReviewState, dict[ReviewAction, ReviewState]] = {
    ReviewState.DRAFT: {
        ReviewAction.SUBMIT_FOR_REVIEW: ReviewState.IN_REVIEW,
    },
    ReviewState.IN_REVIEW: {
        ReviewAction.APPROVE: ReviewState.APPROVED,
        ReviewAction.REQUEST_CHANGES: ReviewState.CHANGES_REQUESTED,
    },
    ReviewState.CHANGES_REQUESTED: {
        ReviewAction.RESUBMIT: ReviewState.IN_REVIEW,
    },
    ReviewState.APPROVED: {
        ReviewAction.MARK_DELIVERED: ReviewState.DELIVERED,
        ReviewAction.REOPEN: ReviewState.DRAFT,
        ReviewAction.AUTO_REVERT: ReviewState.DRAFT,
    },
    ReviewState.DELIVERED: {
        ReviewAction.REOPEN: ReviewState.DRAFT,
        ReviewAction.AUTO_REVERT: ReviewState.DRAFT,
    },
}


@dataclass(frozen=True)
class TransitionResult:
    """Return shape from :func:`apply_transition`. ``ok`` is True
    when the transition is structurally legal; ``reason`` carries a
    short human-readable message when False so the API layer can
    surface it directly."""

    ok: bool
    from_state: ReviewState
    to_state: ReviewState | None
    reason: str = ""


def _coerce(state: ReviewState | str) -> ReviewState:
    """Permit callers to pass a string or an enum interchangeably —
    DB rows come back as plain text, code paths build with the
    enum. ``ValueError`` flows up to the caller for invalid input."""
    return state if isinstance(state, ReviewState) else ReviewState(state)


def _coerce_action(action: ReviewAction | str) -> ReviewAction:
    return action if isinstance(action, ReviewAction) else ReviewAction(action)


def can_transition(from_state: ReviewState | str, action: ReviewAction | str) -> bool:
    """Return True if ``action`` is a structurally valid transition
    out of ``from_state``. Does NOT consult the authorisation layer
    — pair with :func:`authorization.authorize_action` before
    committing.
    """
    fs = _coerce(from_state)
    a = _coerce_action(action)
    return a in _TRANSITIONS.get(fs, {})


def next_state(from_state: ReviewState | str, action: ReviewAction | str) -> ReviewState:
    """Return the destination state for a legal transition.
    ``ValueError`` if the transition isn't in the table — callers
    should ``can_transition`` first if they want a boolean check.
    """
    fs = _coerce(from_state)
    a = _coerce_action(action)
    target = _TRANSITIONS.get(fs, {}).get(a)
    if target is None:
        raise ValueError(
            f"no transition: {fs.value} --{a.value}--> ?  "
            f"(legal actions from {fs.value}: "
            f"{[k.value for k in _TRANSITIONS.get(fs, {})]})"
        )
    return target


def apply_transition(
    from_state: ReviewState | str,
    action: ReviewAction | str,
) -> TransitionResult:
    """Combined ``can_transition`` + ``next_state`` with a structured
    return type. Useful for callers that want one call + a reason
    string on failure instead of two boolean lookups.
    """
    try:
        fs = _coerce(from_state)
    except ValueError as e:
        return TransitionResult(
            ok=False, from_state=ReviewState.DRAFT, to_state=None,
            reason=f"invalid_from_state: {e}",
        )
    try:
        a = _coerce_action(action)
    except ValueError as e:
        return TransitionResult(
            ok=False, from_state=fs, to_state=None,
            reason=f"invalid_action: {e}",
        )
    if not can_transition(fs, a):
        legal = sorted(k.value for k in _TRANSITIONS.get(fs, {}))
        return TransitionResult(
            ok=False, from_state=fs, to_state=None,
            reason=(
                f"action {a.value!r} is not a legal transition from "
                f"{fs.value!r}. Legal actions: {legal or '(none)'}"
            ),
        )
    return TransitionResult(
        ok=True, from_state=fs, to_state=next_state(fs, a), reason="",
    )


def legal_actions(from_state: ReviewState | str) -> list[ReviewAction]:
    """The set of actions that can structurally fire from
    ``from_state``. Useful for the workspace UI to enable / disable
    review buttons. Authorisation gating still applies separately.
    """
    fs = _coerce(from_state)
    return sorted(_TRANSITIONS.get(fs, {}).keys(), key=lambda a: a.value)


__all__ = [
    "ReviewAction",
    "ReviewState",
    "TransitionResult",
    "apply_transition",
    "can_transition",
    "legal_actions",
    "next_state",
]
