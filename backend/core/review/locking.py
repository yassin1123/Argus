"""Lock semantics for review-state — Phase 4 / Week 15 / Day 1.

A session is **locked** when its ``review_state`` is in a terminal
position (``approved`` or ``delivered``). Locked sessions are
visible / readable / exportable but should refuse mutating
operations until they're reopened or auto-reverted.

Today's module is logic-only — two predicates and the lock-state
set. The W15/D2 work wires these into the edit-detection layer
(memo writes, section-deepening accepts) so an attempted mutation
on a locked engagement either:

  - Refuses with a clear error (the strict path — Phase 4 default), OR
  - Auto-reverts the engagement back to ``draft`` via the
    ``ReviewAction.AUTO_REVERT`` transition (the permissive path —
    opt-in per firm, Phase 4 follow-on).

This module doesn't decide WHICH of those two policies fires; it
just answers "is this session currently locked?" and "would this
edit warrant a revert?". The orchestrator owns the policy choice.
"""

from __future__ import annotations

from typing import Any

from .state_machine import ReviewState


# The set of states that mean "no edits without an explicit reopen".
# Keep in one place so :func:`is_locked` and the W15/D2 edit-detector
# stay in lockstep.
_LOCKED_STATES: frozenset[ReviewState] = frozenset({
    ReviewState.APPROVED,
    ReviewState.DELIVERED,
})


def _read_state(session: dict[str, Any] | Any) -> str:
    """Pull ``review_state`` off the session arg — accepts dict or
    object. Falls back to the default ``'draft'`` when the column is
    absent (e.g. sessions created before migration 036 applied)."""
    if isinstance(session, dict):
        v = session.get("review_state")
    else:
        v = getattr(session, "review_state", None)
    return str(v) if v else ReviewState.DRAFT.value


def is_locked(session: dict[str, Any] | Any) -> bool:
    """True when the session's ``review_state`` puts it in a
    locked-for-edits position. Pair with
    :func:`should_auto_revert_on_edit` at the edit-detection layer
    to decide whether to refuse the edit or downgrade the state.
    """
    state = _read_state(session)
    try:
        return ReviewState(state) in _LOCKED_STATES
    except ValueError:
        # Unknown state value — treat as unlocked. The state-machine
        # writes the column with a CHECK-constrained value, so this
        # path only fires when the column is genuinely garbage. The
        # cautious default is "don't refuse the edit" because the
        # alternative (refusing every write) is worse than letting
        # the orchestrator's own validation catch the bad row.
        return False


def should_auto_revert_on_edit(session: dict[str, Any] | Any) -> bool:
    """True when an in-flight edit (memo write, section-deepening
    accept, artifact regeneration with non-trivial payload diff)
    is being attempted on a locked engagement.

    Today this is logically equivalent to :func:`is_locked` — the
    W15/D2 work plugs a more nuanced policy in (e.g. "regenerating
    an artifact doesn't count as an edit; only payload-changing
    writes do"). Keeping the predicate distinct now means the W15/D2
    refactor doesn't have to chase callers.
    """
    return is_locked(session)


__all__ = ["is_locked", "should_auto_revert_on_edit"]
