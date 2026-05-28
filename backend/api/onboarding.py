"""Pilot onboarding API — Phase 5 / Week 24 / Day 2.

The backend the in-app onboarding wizard calls. Every mutation is
scoped to the CALLER's own firm (their ``default_firm_id``) and
gated on firm-admin, so a firm_admin can configure their fresh firm
but can't touch anyone else's.

The endpoints reuse the SAME idempotent functions the operator CLI
runs (``tools/pilot_setup.py``), so the wizard path and the
operator path can't drift:

  POST /api/onboarding/firm/branding   step 1 — name + branding
  POST /api/onboarding/team            step 2 — invite a teammate
  POST /api/onboarding/engagement      step 4 — first engagement
  GET  /api/onboarding/briefs          template briefs (reference)
  GET  /api/onboarding/status          progress (for pause/resume)

Step 3 (library upload) reuses the existing W14 endpoint
``POST /api/firms/{firm_id}/library``; the wizard calls that
directly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.firm_permissions import require_firm_admin, require_firm_member
from db.connection import acquire

# Reuse the operator-CLI functions so wizard + CLI share one path.
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from tools.pilot_setup import (  # noqa: E402
    add_user, create_engagement, create_firm, valid_modes,
)
from eval.pilot_briefs import load_pilot_briefs  # noqa: E402

router = APIRouter()


# ---------------------------------------------------------------------------
# Caller-firm resolution
# ---------------------------------------------------------------------------


async def _caller_firm(user: dict) -> tuple[str, str, str]:
    """Return ``(firm_id, slug, name)`` for the caller's default
    firm. 400 if the caller has no firm (shouldn't happen for a
    firm_admin)."""
    firm_id = user.get("default_firm_id")
    if not firm_id:
        raise HTTPException(
            status_code=400, detail="No firm associated with this user.",
        )
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT slug, name FROM firms WHERE id = $1::uuid", firm_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Firm not found")
    return str(firm_id), row["slug"], row["name"]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class BrandingBody(BaseModel):
    name: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    footer_text: str | None = None
    logo_url: str | None = None


class TeamMemberBody(BaseModel):
    email: str = Field(min_length=3)
    name: str = Field(min_length=1)
    role: str = Field(pattern="^(firm_admin|firm_member)$")


class EngagementBody(BaseModel):
    brief: str = Field(min_length=10)
    mode: str
    lead_email: str
    reviewer_email: str | None = None
    title: str | None = None


# ---------------------------------------------------------------------------
# Step 1 — firm branding
# ---------------------------------------------------------------------------


@router.post("/onboarding/firm/branding")
async def set_firm_branding(
    body: BrandingBody, user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    firm_id, slug, name = await _caller_firm(user)
    await require_firm_admin(firm_id, user, resource_kind="onboarding")
    result = await create_firm(
        name=body.name or name,
        slug=slug,  # existing slug → updates, never creates a 2nd firm
        primary_color=body.primary_color,
        secondary_color=body.secondary_color,
        footer_text=body.footer_text,
        logo_url=body.logo_url,
    )
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Step 2 — invite team
# ---------------------------------------------------------------------------


@router.post("/onboarding/team")
async def invite_team_member(
    body: TeamMemberBody, user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    firm_id, slug, _ = await _caller_firm(user)
    await require_firm_admin(firm_id, user, resource_kind="onboarding")
    result = await add_user(
        firm_slug=slug, email=body.email,
        role=body.role, name=body.name,
    )
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Step 4 — first engagement
# ---------------------------------------------------------------------------


@router.post("/onboarding/engagement")
async def create_first_engagement(
    body: EngagementBody, user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    firm_id, slug, _ = await _caller_firm(user)
    # Creating an engagement is a member action; a firm_admin is a
    # member too. Members may run engagements.
    await require_firm_member(firm_id, user, resource_kind="onboarding")
    if body.mode not in valid_modes():
        raise HTTPException(
            status_code=400,
            detail=f"unknown mode {body.mode!r}; valid: {sorted(valid_modes())}",
        )
    try:
        result = await create_engagement(
            firm_slug=slug, brief=body.brief, mode=body.mode,
            lead_email=body.lead_email,
            reviewer_email=body.reviewer_email, title=body.title,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Template briefs
# ---------------------------------------------------------------------------


@router.get("/onboarding/briefs")
async def get_template_briefs(
    mode: str | None = None, user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    briefs = load_pilot_briefs(mode)
    return {
        "modes": {
            m: [b.to_dict() for b in items]
            for m, items in briefs.items()
        }
    }


# ---------------------------------------------------------------------------
# Progress / resume
# ---------------------------------------------------------------------------


@router.get("/onboarding/status")
async def onboarding_status(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """The four-step progress the wizard reads to resume where the
    operator left off. Each step is 'done' when its side effect is
    visible in the firm's state — so a firm set up via the operator
    CLI shows correct progress in the wizard, and vice versa."""
    firm_id, slug, name = await _caller_firm(user)
    await require_firm_member(firm_id, user, resource_kind="onboarding")

    async with acquire() as conn:
        firm = await conn.fetchrow(
            "SELECT branding FROM firms WHERE id = $1::uuid", firm_id,
        )
        team_count = await conn.fetchval(
            "SELECT COUNT(*)::int FROM firm_memberships WHERE firm_id = $1::uuid",
            firm_id,
        )
        library_count = await conn.fetchval(
            "SELECT COUNT(*)::int FROM firm_content WHERE firm_id = $1::uuid",
            firm_id,
        )
        engagement_count = await conn.fetchval(
            "SELECT COUNT(*)::int FROM sessions WHERE firm_id = $1::uuid",
            firm_id,
        )

    import json as _json
    branding = firm["branding"] if firm else None
    if isinstance(branding, str):
        try: branding = _json.loads(branding)
        except Exception: branding = {}
    branding = branding or {}

    steps = {
        "firm_setup": bool(branding),
        "invite_team": int(team_count or 0) > 1,  # >1 = beyond the admin
        "upload_library": int(library_count or 0) > 0,
        "first_engagement": int(engagement_count or 0) > 0,
    }
    return {
        "firm_id": firm_id, "slug": slug, "name": name,
        "steps": steps,
        "complete": all(steps.values()),
        "counts": {
            "team_members": int(team_count or 0),
            "library_documents": int(library_count or 0),
            "engagements": int(engagement_count or 0),
        },
    }


__all__ = ["router"]
