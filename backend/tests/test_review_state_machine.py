"""Phase 4 / Week 15 / Day 1 — review state machine + authorization tests.

Ten tests per spec covering:
  1.  Valid transition: draft → in_review via submit_for_review.
  2.  Invalid transition: draft cannot skip to approved.
  3.  Invalid transition: approved cannot go back to in_review (must
      go through draft via reopen).
  4.  Self-approval guard: author == reviewer is denied by default.
  5.  Self-approval permitted when ``firms.allow_self_approval`` is True.
  6.  Member without admin role or reviewer assignment is denied
      approval.
  7.  Admin can approve.
  8.  An explicit reviewer assignment lets a non-admin approve.
  9.  reopen requires admin role.
  10. is_locked returns True when state is approved (and delivered).

Pure-logic tests — no DB, no API.
"""

from __future__ import annotations

import pytest

from core.review import (
    AuthorizationResult,
    ReviewAction,
    ReviewState,
    apply_transition,
    authorize_action,
    can_transition,
    is_locked,
    legal_actions,
    next_state,
    should_auto_revert_on_edit,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _admin(uid: str = "u-admin") -> dict:
    return {"id": uid, "firm_role": "admin"}


def _member(uid: str) -> dict:
    return {"id": uid, "firm_role": "member"}


def _session(
    *, author: str = "u-author", reviewer: str | None = None,
    state: str = "in_review",
) -> dict:
    return {
        "id": "sess-1",
        "created_by_user_id": author,
        "review_assigned_to": reviewer or "",
        "review_state": state,
    }


def _firm(*, allow_self_approval: bool = False) -> dict:
    return {"id": "firm-1", "allow_self_approval": allow_self_approval}


# ---------------------------------------------------------------------------
# Test 1 — valid draft → in_review
# ---------------------------------------------------------------------------


def test_valid_transition_draft_to_in_review() -> None:
    assert can_transition(ReviewState.DRAFT, ReviewAction.SUBMIT_FOR_REVIEW) is True
    assert next_state(ReviewState.DRAFT, ReviewAction.SUBMIT_FOR_REVIEW) == ReviewState.IN_REVIEW
    res = apply_transition("draft", "submit_for_review")
    assert res.ok and res.to_state == ReviewState.IN_REVIEW
    # Sanity: legal_actions surfaces the same action.
    assert ReviewAction.SUBMIT_FOR_REVIEW in legal_actions(ReviewState.DRAFT)


# ---------------------------------------------------------------------------
# Test 2 — invalid draft → approved (no skip)
# ---------------------------------------------------------------------------


def test_invalid_transition_draft_to_approved_blocked() -> None:
    assert can_transition(ReviewState.DRAFT, ReviewAction.APPROVE) is False
    res = apply_transition(ReviewState.DRAFT, ReviewAction.APPROVE)
    assert res.ok is False
    assert res.to_state is None
    assert "not a legal transition" in res.reason
    # The reason names the legal options so the API can surface them.
    assert "submit_for_review" in res.reason


# ---------------------------------------------------------------------------
# Test 3 — invalid approved → in_review (no back-edge except via draft)
# ---------------------------------------------------------------------------


def test_invalid_transition_approved_to_in_review_blocked() -> None:
    # From APPROVED the only legal actions are mark_delivered, reopen,
    # auto_revert. Going straight back to IN_REVIEW isn't one of them.
    for action in (ReviewAction.SUBMIT_FOR_REVIEW, ReviewAction.RESUBMIT,
                   ReviewAction.APPROVE, ReviewAction.REQUEST_CHANGES):
        assert can_transition(ReviewState.APPROVED, action) is False, (
            f"approved → {action.value} should be rejected"
        )
    # And the legal options are exactly the three we expect.
    legal = legal_actions(ReviewState.APPROVED)
    assert set(legal) == {
        ReviewAction.MARK_DELIVERED, ReviewAction.REOPEN, ReviewAction.AUTO_REVERT,
    }


# ---------------------------------------------------------------------------
# Test 4 — author cannot approve own work by default
# ---------------------------------------------------------------------------


def test_author_cannot_approve_own_work_by_default() -> None:
    # The actor IS the author. Firm doesn't permit self-approval.
    author_admin = {"id": "u-1", "firm_role": "admin"}
    session = _session(author="u-1", state="in_review")
    firm = _firm(allow_self_approval=False)

    res = authorize_action(ReviewAction.APPROVE, actor=author_admin, session=session, firm=firm)
    assert isinstance(res, AuthorizationResult)
    assert res.allowed is False
    assert "self-approval" in res.reason.lower()


# ---------------------------------------------------------------------------
# Test 5 — self-approval allowed when firm flag is True
# ---------------------------------------------------------------------------


def test_author_can_approve_own_work_when_firm_allows() -> None:
    author_admin = {"id": "u-1", "firm_role": "admin"}
    session = _session(author="u-1", state="in_review")
    firm = _firm(allow_self_approval=True)

    res = authorize_action(ReviewAction.APPROVE, actor=author_admin, session=session, firm=firm)
    assert res.allowed is True, f"unexpected denial: {res.reason}"


# ---------------------------------------------------------------------------
# Test 6 — non-admin non-assigned-reviewer member is denied approval
# ---------------------------------------------------------------------------


def test_member_cannot_approve() -> None:
    member = _member("u-2")
    session = _session(author="u-author", reviewer=None, state="in_review")
    firm = _firm()

    res = authorize_action(ReviewAction.APPROVE, actor=member, session=session, firm=firm)
    assert res.allowed is False
    assert "firm admin" in res.reason.lower() or "reviewer" in res.reason.lower()

    # Same gate fires on request_changes.
    res2 = authorize_action(ReviewAction.REQUEST_CHANGES, actor=member, session=session, firm=firm)
    assert res2.allowed is False


# ---------------------------------------------------------------------------
# Test 7 — admin can approve (not the author; segregation holds)
# ---------------------------------------------------------------------------


def test_admin_can_approve() -> None:
    admin = _admin("u-admin")
    session = _session(author="u-other", reviewer=None, state="in_review")
    firm = _firm()

    res = authorize_action(ReviewAction.APPROVE, actor=admin, session=session, firm=firm)
    assert res.allowed is True, f"unexpected denial: {res.reason}"

    # And request_changes is symmetric.
    res2 = authorize_action(ReviewAction.REQUEST_CHANGES, actor=admin, session=session, firm=firm)
    assert res2.allowed is True


# ---------------------------------------------------------------------------
# Test 8 — assigned reviewer can approve even if they're a member
# ---------------------------------------------------------------------------


def test_assigned_reviewer_can_approve_even_if_member() -> None:
    member_assigned = _member("u-assigned")
    session = _session(author="u-author", reviewer="u-assigned", state="in_review")
    firm = _firm()

    res = authorize_action(ReviewAction.APPROVE, actor=member_assigned, session=session, firm=firm)
    assert res.allowed is True, f"unexpected denial: {res.reason}"

    # An OTHER member without the assignment still gets denied.
    other_member = _member("u-other-member")
    res2 = authorize_action(ReviewAction.APPROVE, actor=other_member, session=session, firm=firm)
    assert res2.allowed is False


# ---------------------------------------------------------------------------
# Test 9 — reopen requires admin
# ---------------------------------------------------------------------------


def test_reopen_requires_admin() -> None:
    session = _session(author="u-other", state="approved")
    firm = _firm()

    # Member → denied.
    res = authorize_action(ReviewAction.REOPEN, actor=_member("u-2"), session=session, firm=firm)
    assert res.allowed is False
    assert "admin" in res.reason.lower()

    # Admin → allowed.
    res2 = authorize_action(ReviewAction.REOPEN, actor=_admin("u-admin"), session=session, firm=firm)
    assert res2.allowed is True

    # Even an assigned reviewer who's a member can't reopen.
    session_with_assigned = _session(
        author="u-author", reviewer="u-assigned", state="approved",
    )
    res3 = authorize_action(
        ReviewAction.REOPEN,
        actor=_member("u-assigned"),
        session=session_with_assigned,
        firm=firm,
    )
    assert res3.allowed is False, "reopen must be admin-only — assignment doesn't unlock it"


# ---------------------------------------------------------------------------
# Test 10 — is_locked when approved (and delivered)
# ---------------------------------------------------------------------------


def test_is_locked_when_approved() -> None:
    # Locked-for-edits states.
    assert is_locked({"review_state": "approved"}) is True
    assert is_locked({"review_state": "delivered"}) is True
    assert should_auto_revert_on_edit({"review_state": "approved"}) is True
    assert should_auto_revert_on_edit({"review_state": "delivered"}) is True

    # Open states.
    assert is_locked({"review_state": "draft"}) is False
    assert is_locked({"review_state": "in_review"}) is False
    assert is_locked({"review_state": "changes_requested"}) is False
    assert should_auto_revert_on_edit({"review_state": "draft"}) is False

    # Missing column defaults to draft → unlocked.
    assert is_locked({}) is False
    # Unknown state is treated cautiously — unlocked (so the edit-detector
    # doesn't refuse writes on a malformed row).
    assert is_locked({"review_state": "not_a_real_state"}) is False


# ---------------------------------------------------------------------------
# Bonus assertions on the state-machine completeness (every state has
# at least one legal action; auto_revert is system-only at the auth layer).
# ---------------------------------------------------------------------------


def test_state_machine_completeness_and_auto_revert_is_system_only() -> None:
    # Every state except DELIVERED has at least one user-driven legal
    # action. DELIVERED has REOPEN + AUTO_REVERT; REOPEN is user-driven.
    for state in ReviewState:
        actions = legal_actions(state)
        # The terminal-ish states (APPROVED, DELIVERED) include
        # auto_revert; everything else has at least one user action.
        user_actions = [a for a in actions if a != ReviewAction.AUTO_REVERT]
        if state == ReviewState.DELIVERED:
            # DELIVERED has REOPEN (admin-only escape hatch) +
            # AUTO_REVERT (system). At least REOPEN is user-driven.
            assert ReviewAction.REOPEN in user_actions
        else:
            assert user_actions, f"state {state.value} has no user actions"

    # auto_revert is rejected by the authorisation layer for any user
    # (system-only).
    firm = _firm()
    res_admin = authorize_action(
        ReviewAction.AUTO_REVERT,
        actor=_admin("u-admin"),
        session=_session(state="approved"),
        firm=firm,
    )
    assert res_admin.allowed is False
    assert "system action" in res_admin.reason.lower()
