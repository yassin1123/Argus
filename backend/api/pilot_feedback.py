"""Pilot feedback API — Phase 5 / Week 24 / Day 3.

One-click, optional feedback surfaces. Every write is firm-scoped:
the session's firm is resolved and the caller is checked against it
via the W23 firm-scope guard (cross-firm → 404, anti-enumeration).

  POST /api/sessions/{id}/claims/{claim_id}/feedback   per-claim
  POST /api/sessions/{id}/artifacts/rating             per-artifact
  GET  /api/pilot/checkin/form                          the questions
  POST /api/pilot/checkin                               weekly check-in
  GET  /api/pilot/health                                pilot dashboard
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.firm_permissions import require_firm_admin
from auth.firm_scope import assert_firm_access, get_session_firm_id
from core.pilot_feedback import (
    CHECKIN_QUESTIONS,
    CLAIM_ASSESSMENTS,
    pilot_health_panel,
    record_artifact_rating,
    record_claim_feedback,
    submit_checkin,
)

# Session-scoped routes mount under /api/sessions; pilot-level routes
# under /api/pilot.
session_router = APIRouter()
router = APIRouter()


async def _session_firm_or_404(session_id: str, user: dict) -> str:
    """Resolve the session's firm + enforce the caller belongs to it.
    Returns the firm_id. 404 on any cross-firm / missing case."""
    firm_id = await get_session_firm_id(session_id)
    await assert_firm_access(
        user=user, resource_firm_id=firm_id,
        resource_kind="session", resource_id=session_id,
    )
    return firm_id  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Per-claim verification feedback
# ---------------------------------------------------------------------------


class ClaimFeedbackBody(BaseModel):
    consultant_assessment: str = Field(
        description=f"one of {CLAIM_ASSESSMENTS}",
    )
    verdict_at_feedback: str | None = None
    note: str | None = Field(default=None, max_length=2000)


@session_router.post("/{session_id}/claims/{claim_id}/feedback", status_code=201)
async def post_claim_feedback(
    session_id: str = Path(...),
    claim_id: str = Path(...),
    body: ClaimFeedbackBody = ...,  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    firm_id = await _session_firm_or_404(session_id, user)
    if body.consultant_assessment not in CLAIM_ASSESSMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"consultant_assessment must be one of {CLAIM_ASSESSMENTS}",
        )
    fid = await record_claim_feedback(
        session_id=session_id, firm_id=firm_id, claim_id=claim_id,
        consultant_assessment=body.consultant_assessment,
        user_id=user["user_id"],
        verdict_at_feedback=body.verdict_at_feedback, note=body.note,
    )
    return {"ok": True, "feedback_id": fid}


# ---------------------------------------------------------------------------
# Per-artifact quality rating
# ---------------------------------------------------------------------------


class ArtifactRatingBody(BaseModel):
    rating: int = Field(ge=1, le=5)
    artifact_id: str | None = None
    artifact_type: str | None = None
    comment: str | None = Field(default=None, max_length=2000)


@session_router.post("/{session_id}/artifacts/rating", status_code=201)
async def post_artifact_rating(
    session_id: str = Path(...),
    body: ArtifactRatingBody = ...,  # type: ignore[assignment]
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    firm_id = await _session_firm_or_404(session_id, user)
    rid = await record_artifact_rating(
        session_id=session_id, firm_id=firm_id,
        rating=body.rating, user_id=user["user_id"],
        artifact_id=body.artifact_id, artifact_type=body.artifact_type,
        comment=body.comment,
    )
    return {"ok": True, "rating_id": rid}


# ---------------------------------------------------------------------------
# Weekly check-in
# ---------------------------------------------------------------------------


class CheckinBody(BaseModel):
    responses: dict[str, Any]
    week_bucket: str | None = None


@router.get("/pilot/checkin/form")
async def get_checkin_form(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    return {"questions": CHECKIN_QUESTIONS}


@router.post("/pilot/checkin", status_code=201)
async def post_checkin(
    body: CheckinBody, user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    firm_id = user.get("default_firm_id")
    if not firm_id:
        raise HTTPException(status_code=400, detail="No firm for this user.")
    # The weekly check-in is a firm_admin action (the pilot lead).
    await require_firm_admin(firm_id, user, resource_kind="pilot_checkin")
    result = await submit_checkin(
        firm_id=firm_id, user_id=user["user_id"],
        responses=body.responses, week_bucket=body.week_bucket,
    )
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Pilot health dashboard
# ---------------------------------------------------------------------------


@router.get("/pilot/health")
async def get_pilot_health(
    firm_id: str | None = None,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """The pilot-health aggregate. A firm_admin sees their own firm;
    a system_admin may scope to any firm via ?firm_id. Cross-firm data
    is never visible to a firm_admin."""
    is_system_admin = user.get("role") == "admin"
    if is_system_admin:
        target = firm_id or user.get("default_firm_id")
    else:
        target = user.get("default_firm_id")  # forced — ignore any override
    if not target:
        raise HTTPException(status_code=400, detail="No firm to report on.")
    # Firm-admin must be an admin of the firm they're reading.
    if not is_system_admin:
        await require_firm_admin(target, user, resource_kind="pilot_health")
    return await pilot_health_panel(target)


__all__ = ["router", "session_router"]
