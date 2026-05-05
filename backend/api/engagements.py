"""Engagement membership management — invite, role change, remove."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.permissions import (
    add_membership,
    can_admin,
    can_read,
    list_memberships,
    remove_membership,
)
from auth.queries import get_user_by_email, get_user_by_id
from core.limits import limiter
from db.queries import get_session_row

router = APIRouter()


class AddMemberBody(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: Literal["lead", "member", "viewer"] = "member"


@router.get("/{engagement_id}/members")
async def list_members(engagement_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    if not await get_session_row(engagement_id):
        raise HTTPException(status_code=404, detail="Engagement not found")
    if not await can_read(engagement_id, user):
        raise HTTPException(status_code=404, detail="Engagement not found")
    members = await list_memberships(engagement_id)
    return {"members": members}


@router.post("/{engagement_id}/members", status_code=201)
@limiter.limit("60/hour")
async def add_member(
    request: Request,
    engagement_id: str,
    body: AddMemberBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if not await get_session_row(engagement_id):
        raise HTTPException(status_code=404, detail="Engagement not found")
    if not await can_admin(engagement_id, user):
        raise HTTPException(status_code=403, detail="Lead-only action")

    target = await get_user_by_email(body.email)
    if not target:
        raise HTTPException(status_code=404, detail="No user with that email")
    await add_membership(engagement_id, target["id"], body.role, added_by=user["user_id"])
    return {
        "user_id": target["id"],
        "email": target["email"],
        "full_name": target["full_name"],
        "role": body.role,
    }


@router.delete("/{engagement_id}/members/{user_id}")
async def remove_member(
    engagement_id: str,
    user_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    if not await get_session_row(engagement_id):
        raise HTTPException(status_code=404, detail="Engagement not found")
    if not await can_admin(engagement_id, user):
        raise HTTPException(status_code=403, detail="Lead-only action")

    target = await get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    # Don't let a lead remove themselves if they're the only lead — would orphan the engagement.
    members = await list_memberships(engagement_id)
    leads = [m for m in members if m["role"] == "lead"]
    if (
        target["id"] == user["user_id"]
        and len(leads) == 1
        and leads[0]["user_id"] == user["user_id"]
    ):
        raise HTTPException(
            status_code=409,
            detail="You're the only lead — promote someone else first.",
        )

    ok = await remove_membership(engagement_id, target["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"removed": True}
