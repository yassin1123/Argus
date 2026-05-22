"""Role + actor gating for review actions — Phase 4 / Week 15 / Day 1.

Pure logic. Takes loosely-typed dict-shaped ``actor`` / ``session`` /
``firm`` arguments so the same function works against asyncpg rows,
ORM objects, or hand-rolled fixtures. The DB-fetch is the caller's
job (W15/D2 wires that).

The four enforced rules:

  1. ``submit_for_review`` / ``resubmit`` / ``mark_delivered`` — any
     firm member on the firm. Reasoning: the consultant who built
     the engagement is the one who knows when it's ready; locking
     submission behind admin approval would create a queue Phase 4
     doesn't want.
  2. ``approve`` / ``request_changes`` — only a firm admin OR the
     explicitly assigned reviewer (``sessions.review_assigned_to``).
     AND (actor != author) UNLESS ``firms.allow_self_approval`` is
     True. Default firm setting is False; the seg-of-duties guard
     is what makes the workflow trustworthy.
  3. ``reopen`` — firm admin only. Reopening a delivered engagement
     is rare + consequential; non-admins can request changes via the
     comment thread (W16 work) but can't unilaterally re-enter the
     lifecycle.
  4. ``auto_revert`` — system action only; no user can fire it via
     the API. The locking helper (W15/D2 edit-detection) is the only
     legitimate trigger.

Returns :class:`AuthorizationResult(allowed: bool, reason: str)`.
The string is human-readable and surfaceable directly in the API's
403 body.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .state_machine import ReviewAction


@dataclass(frozen=True)
class AuthorizationResult:
    """Return shape of :func:`authorize_action`. The reason is
    surfaceable directly in the API's 403 response body — keep it
    concise and informative; no internal-id leakage."""

    allowed: bool
    reason: str = ""


# Canonical firm-membership roles. The DB CHECK constraint (migration
# 024) allows only ``admin`` / ``member``; W15's spec talks about
# ``firm_admin`` / ``firm_member`` — we accept either spelling.
_ADMIN_ROLES = {"admin", "firm_admin"}
_MEMBER_ROLES = {"member", "firm_member"} | _ADMIN_ROLES


def _firm_role(actor: dict[str, Any] | Any) -> str:
    """Pull the firm-membership role off the actor dict. Falls back
    to ``''`` if absent — caller's :class:`AuthorizationResult`
    handles the non-member case with a clean reason."""
    if isinstance(actor, dict):
        return str(actor.get("firm_role") or actor.get("role") or "").strip().lower()
    return str(getattr(actor, "firm_role", "") or getattr(actor, "role", "") or "").strip().lower()


def _actor_id(actor: dict[str, Any] | Any) -> str:
    if isinstance(actor, dict):
        return str(actor.get("id") or actor.get("user_id") or "")
    return str(getattr(actor, "id", "") or getattr(actor, "user_id", "") or "")


def _author_id(session: dict[str, Any] | Any) -> str:
    if isinstance(session, dict):
        return str(session.get("created_by_user_id") or session.get("author_id") or "")
    return str(getattr(session, "created_by_user_id", "") or getattr(session, "author_id", "") or "")


def _reviewer_id(session: dict[str, Any] | Any) -> str:
    if isinstance(session, dict):
        return str(session.get("review_assigned_to") or "")
    return str(getattr(session, "review_assigned_to", "") or "")


def _allow_self_approval(firm: dict[str, Any] | Any) -> bool:
    if isinstance(firm, dict):
        return bool(firm.get("allow_self_approval"))
    return bool(getattr(firm, "allow_self_approval", False))


def _is_admin(role: str) -> bool:
    return role in _ADMIN_ROLES


def _is_member(role: str) -> bool:
    return role in _MEMBER_ROLES


def authorize_action(
    action: ReviewAction | str,
    *,
    actor: dict[str, Any] | Any,
    session: dict[str, Any] | Any,
    firm: dict[str, Any] | Any,
) -> AuthorizationResult:
    """Enforce the four W15/D1 rules. Returns ``AuthorizationResult``;
    callers should refuse the API call when ``allowed`` is False
    using the included ``reason`` as the 403 body.

    The function does NOT consult the state machine — call
    :func:`state_machine.can_transition` first to confirm the
    transition is legal, THEN call this to confirm the actor is
    allowed to fire it. The two checks are deliberately decoupled
    so an invalid-state error reads differently from a permission
    error in the UI.
    """
    if isinstance(action, str):
        try:
            action = ReviewAction(action)
        except ValueError:
            return AuthorizationResult(False, f"unknown action: {action!r}")

    actor_id = _actor_id(actor)
    role = _firm_role(actor)

    if not actor_id:
        return AuthorizationResult(False, "actor has no id (not authenticated?)")
    if not _is_member(role):
        return AuthorizationResult(
            False,
            f"actor role {role!r} is not a firm member — "
            f"must be one of {sorted(_MEMBER_ROLES)}",
        )

    # auto_revert is system-only. No path through this function permits
    # it; if a caller ever requests it via the API surface, we refuse.
    if action == ReviewAction.AUTO_REVERT:
        return AuthorizationResult(
            False,
            "auto_revert is a system action; users cannot fire it directly. "
            "Edit the engagement to trigger the lock-revert path.",
        )

    # Bucket 1: any member can submit / resubmit / mark delivered.
    if action in (
        ReviewAction.SUBMIT_FOR_REVIEW,
        ReviewAction.RESUBMIT,
        ReviewAction.MARK_DELIVERED,
    ):
        return AuthorizationResult(True, "")

    # Bucket 2: approve / request_changes — admin OR assigned reviewer,
    # with the self-approval guard.
    if action in (ReviewAction.APPROVE, ReviewAction.REQUEST_CHANGES):
        is_admin = _is_admin(role)
        reviewer_id = _reviewer_id(session)
        is_assigned_reviewer = bool(reviewer_id) and actor_id == reviewer_id

        if not (is_admin or is_assigned_reviewer):
            return AuthorizationResult(
                False,
                f"action {action.value!r} requires either firm admin role "
                f"or an explicit reviewer assignment matching the actor.",
            )

        # Self-approval guard fires only for the APPROVE action.
        # request_changes can legitimately be fired on one's own work
        # (the consultant flagging their own draft to themselves makes
        # no sense, but a partner-author flagging their own piece for
        # revision is benign — we don't gate it).
        if action == ReviewAction.APPROVE:
            author_id = _author_id(session)
            if author_id and actor_id == author_id and not _allow_self_approval(firm):
                return AuthorizationResult(
                    False,
                    "self-approval is disabled for this firm (segregation of "
                    "duties). A different firm admin or the assigned reviewer "
                    "must approve. Flip firms.allow_self_approval=true to "
                    "permit it for solo / tiny firms.",
                )
        return AuthorizationResult(True, "")

    # Bucket 3: reopen — admin only.
    if action == ReviewAction.REOPEN:
        if not _is_admin(role):
            return AuthorizationResult(
                False,
                "reopen is restricted to firm admins. Non-admins can request "
                "changes via the comment thread (W16) but cannot unilaterally "
                "re-enter the lifecycle from a terminal state.",
            )
        return AuthorizationResult(True, "")

    return AuthorizationResult(False, f"unhandled action: {action!r}")


__all__ = ["AuthorizationResult", "authorize_action"]
