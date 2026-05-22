"""Review workflow endpoints — Phase 4 / Week 15 / Day 2.

Six endpoints exposing the W15/D1 state machine + the W15/D2
transition service:

  POST /api/sessions/{id}/review/submit          submit_for_review
  POST /api/sessions/{id}/review/approve         approve
  POST /api/sessions/{id}/review/request-changes request_changes
  POST /api/sessions/{id}/review/mark-delivered  mark_delivered
  POST /api/sessions/{id}/review/reopen          reopen
  GET  /api/sessions/{id}/review                 current state + history

Routing: this module's router gets mounted at ``/api/sessions`` in
``main.py`` so the engagement-scoped paths nest under the existing
sessions namespace.

Every endpoint forwards to ``core.review.service.transition_review``;
the service returns a structured ``ReviewTransitionResult`` whose
``status_code`` we map straight to ``HTTPException`` on failure.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.permissions import can_read
from core.review.service import (
    ReviewTransitionResult,
    get_review_state,
    transition_review,
)
from core.review.state_machine import ReviewAction

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class SubmitForReviewBody(BaseModel):
    """``reviewer_id`` is optional — when omitted, the engagement is
    open for any firm admin to pick up (the common case in small
    firms). When set, the named member can approve / request changes
    even without admin role (W15/D1 authorization)."""

    reviewer_id: str | None = Field(default=None, description="Optional user UUID to assign as reviewer.")

    model_config = {"extra": "ignore"}


class RequestChangesBody(BaseModel):
    """``feedback`` is required — request_changes without explanation
    is hostile to the consultant. Surface a clear 400 if missing."""

    feedback: str = Field(..., min_length=1, max_length=4000)

    model_config = {"extra": "ignore"}


class ApproveBody(BaseModel):
    """Empty body permitted — approval needs no payload. Accepting
    an optional comment field lets partners leave a note that
    surfaces on the workspace timeline."""

    note: str | None = Field(default=None, max_length=2000)

    model_config = {"extra": "ignore"}


class ReopenBody(BaseModel):
    """Optional reason — surfaced in the review_records audit row
    and the workspace timeline so the team understands why a
    delivered engagement was reopened."""

    reason: str | None = Field(default=None, max_length=2000)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Permission helper
# ---------------------------------------------------------------------------


async def _require_read(session_id: str, user: dict) -> None:
    """The review endpoints all require at least read access to the
    engagement. Cross-firm callers get a 404 (same shape as the
    rest of the W9/W10 endpoints — don't leak existence)."""
    if not await can_read(session_id, user):
        raise HTTPException(status_code=404, detail="Session not found")


def _result_or_raise(result: ReviewTransitionResult) -> dict[str, Any]:
    """Map a ReviewTransitionResult into the API's success body, or
    raise the appropriate HTTPException on failure."""
    if not result.ok:
        raise HTTPException(status_code=result.status_code, detail=result.reason)
    return {
        "session_id": result.session_id,
        "from_state": result.from_state,
        "to_state": result.to_state,
        "action": result.action,
        "review_record_id": result.review_record_id,
        "reviewer_id": result.reviewer_id,
        "artifacts_marked_stale": result.artifacts_marked_stale,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{session_id}/review/submit")
async def submit_for_review_endpoint(
    session_id: str,
    body: SubmitForReviewBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Move an engagement from draft (or changes_requested) into
    in_review. Any firm member can submit.

    When ``reviewer_id`` is supplied, the assignment is stored on
    ``sessions.review_assigned_to`` so the authorization layer can
    later let the named member approve even without admin role.
    """
    await _require_read(session_id, user)

    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid session id: {e}") from e

    reviewer_uuid: UUID | None = None
    if body.reviewer_id:
        try:
            reviewer_uuid = UUID(body.reviewer_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid reviewer_id: {e}") from e

    # Decide action by current state — submit_for_review on draft,
    # resubmit on changes_requested. Either way the destination is
    # in_review and the API surface stays uniform.
    state = await get_review_state(sid)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    current = state["review_state"]
    action = ReviewAction.RESUBMIT if current == "changes_requested" else ReviewAction.SUBMIT_FOR_REVIEW

    result = await transition_review(
        sid, action, UUID(user["user_id"]), reviewer_id=reviewer_uuid,
    )
    return _result_or_raise(result)


@router.post("/{session_id}/review/approve")
async def approve_endpoint(
    session_id: str,
    body: ApproveBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Approve an in-review engagement. Admin OR assigned reviewer
    only; the author cannot approve their own work unless
    ``firms.allow_self_approval`` is True (default false)."""
    await _require_read(session_id, user)

    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid session id: {e}") from e

    result = await transition_review(
        sid, ReviewAction.APPROVE, UUID(user["user_id"]),
        feedback=body.note,
    )
    return _result_or_raise(result)


@router.post("/{session_id}/review/request-changes")
async def request_changes_endpoint(
    session_id: str,
    body: RequestChangesBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Request changes on an in-review engagement. Same
    authorisation gate as approve. ``feedback`` is required."""
    await _require_read(session_id, user)

    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid session id: {e}") from e

    result = await transition_review(
        sid, ReviewAction.REQUEST_CHANGES, UUID(user["user_id"]),
        feedback=body.feedback,
    )
    return _result_or_raise(result)


@router.post("/{session_id}/review/mark-delivered")
async def mark_delivered_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Move an approved engagement into delivered. Any firm member
    may mark — it's a consultant-driven flag that the bundle has
    been sent to the client."""
    await _require_read(session_id, user)

    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid session id: {e}") from e

    result = await transition_review(
        sid, ReviewAction.MARK_DELIVERED, UUID(user["user_id"]),
    )
    return _result_or_raise(result)


@router.post("/{session_id}/review/reopen")
async def reopen_endpoint(
    session_id: str,
    body: ReopenBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Admin-only: reopen an approved or delivered engagement back
    to draft so it can be edited + re-reviewed."""
    await _require_read(session_id, user)

    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid session id: {e}") from e

    result = await transition_review(
        sid, ReviewAction.REOPEN, UUID(user["user_id"]),
        feedback=body.reason,
    )
    return _result_or_raise(result)


@router.get("/{session_id}/review")
async def get_review_endpoint(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Current review state + the full transition history."""
    await _require_read(session_id, user)

    try:
        sid = UUID(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"invalid session id: {e}") from e

    state = await get_review_state(sid)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return state
