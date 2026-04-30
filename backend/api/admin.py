"""Admin endpoints — audit trail viewer."""

from fastapi import APIRouter, Depends, HTTPException, Query

from audit.queries import list_events_for_engagement, list_recent_events
from auth.dependencies import get_current_user
from auth.permissions import can_admin

router = APIRouter()


@router.get("/audit")
async def audit_log(
    engagement_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    user: dict = Depends(get_current_user),
) -> dict:
    """Read the audit trail.

    - engagement_id provided: must be a lead on that engagement (or firm admin)
    - engagement_id omitted: firm-wide view, firm admins only
    """
    if engagement_id:
        if not await can_admin(engagement_id, user):
            raise HTTPException(status_code=403, detail="Lead-only audit view")
        events = await list_events_for_engagement(engagement_id, limit=limit)
    else:
        if user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Firm admin required")
        events = await list_recent_events(limit=limit)
    return {"events": events}
