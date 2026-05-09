"""Phase 2 / Week 6 / Day 2 — firm-mode admin API.

Endpoints (all under ``/api/firms/{firm_id}/modes``):

  POST   /                        create override / new mode    (admin)
  GET    /                        list overrides + built-ins    (member)
  GET    /{name}                  resolved view + raw config    (member)
  PATCH  /{name}                  update config                 (admin)
  POST   /{name}/retire           soft-delete                   (admin)
  POST   /{name}/restore          un-retire                     (admin)

Permission semantics mirror W5/D3 firm_library:
  - cross-firm reads -> 404 (anti-enumeration)
  - admin-only mutations -> 403 for members, 404 for non-members
  - all denials write a domain-level audit row (firm_modes.*_unauthorized_attempt)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from auth.firm_permissions import require_firm_admin, require_firm_member
from core.consulting_modes.resolver import list_built_in_names, resolve_mode
from core.consulting_modes.service import (
    FirmMode,
    create_firm_mode,
    get_firm_mode,
    list_firm_modes,
    restore_firm_mode,
    retire_firm_mode,
    update_firm_mode,
)
from core.consulting_modes.types import (
    ModeConfigError,
    ModeNotFoundError,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic request/response shapes
# ---------------------------------------------------------------------------


class CreateFirmModeBody(BaseModel):
    """Body for POST /api/firms/{firm_id}/modes."""

    name: str = Field(..., min_length=1, max_length=64)
    base_mode: Optional[str] = Field(default=None, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)


class UpdateFirmModeBody(BaseModel):
    """Body for PATCH /api/firms/{firm_id}/modes/{name}."""

    config: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_error(e: ModeConfigError) -> HTTPException:
    """Map ModeConfigError -> 400 with a structured detail body."""
    return HTTPException(
        status_code=400,
        detail={"error": "invalid_mode_config", "message": str(e)},
    )


# ---------------------------------------------------------------------------
# POST / — create
# ---------------------------------------------------------------------------


@router.post("")
async def create_endpoint(
    body: CreateFirmModeBody,
    firm_id: str = Path(..., description="UUID of the firm"),
    user: dict = Depends(get_current_user),
) -> dict:
    await require_firm_member(firm_id, user, resource_kind="firm_modes")
    await require_firm_admin(firm_id, user, resource_kind="firm_modes")
    try:
        fm = await create_firm_mode(
            firm_id=firm_id,
            name=body.name,
            base_mode=body.base_mode,
            config=body.config,
            created_by=user.get("user_id"),
            actor_email=user.get("email"),
        )
    except ModeConfigError as e:
        raise _config_error(e) from e
    return {"firm_mode": fm.to_dict()}


# ---------------------------------------------------------------------------
# GET / — list (built-ins + firm overrides)
# ---------------------------------------------------------------------------


@router.get("")
async def list_endpoint(
    firm_id: str = Path(...),
    include_retired: bool = Query(default=False),
    user: dict = Depends(get_current_user),
) -> dict:
    await require_firm_member(firm_id, user, resource_kind="firm_modes")
    overrides = await list_firm_modes(firm_id, include_retired=include_retired)
    overrides_by_name = {fm.name: fm for fm in overrides}

    out: list[dict[str, Any]] = []
    for built_in_name in list_built_in_names():
        ov = overrides_by_name.pop(built_in_name, None)
        out.append(
            {
                "name": built_in_name,
                "is_builtin": True,
                "has_firm_override": ov is not None and ov.retired_at is None,
                "firm_override": ov.to_dict() if ov else None,
            }
        )
    # Any remaining overrides are firm-only modes (no built-in counterpart).
    for fm in overrides_by_name.values():
        out.append(
            {
                "name": fm.name,
                "is_builtin": False,
                "has_firm_override": fm.retired_at is None,
                "firm_override": fm.to_dict(),
            }
        )
    out.sort(key=lambda m: m["name"])
    return {"modes": out}


# ---------------------------------------------------------------------------
# GET /{name} — resolved view + raw config
# ---------------------------------------------------------------------------


@router.get("/{name}")
async def get_endpoint(
    firm_id: str = Path(...),
    name: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await require_firm_member(firm_id, user, resource_kind="firm_modes")
    raw = await get_firm_mode(firm_id, name)
    try:
        resolved = await resolve_mode(name, firm_id=firm_id)
    except ModeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "name": name,
        "resolved": _resolved_to_dict(resolved),
        "firm_override": raw.to_dict() if raw else None,
    }


def _resolved_to_dict(m: Any) -> dict[str, Any]:
    return {
        "name": m.name,
        "display_name": m.display_name,
        "description": m.description,
        "required_branches": m.required_branches,
        "reasoning_slots": m.reasoning_slots,
        "source_priorities_default": m.source_priorities_default,
        "trust_tier_rules": m.trust_tier_rules,
        "writer_overlay": m.writer_overlay,
        "planner_overlay": m.planner_overlay,
        "min_evidence_objects": m.min_evidence_objects,
        "metadata": m.metadata,
        "layer_provenance": m.layer_provenance,
    }


# ---------------------------------------------------------------------------
# PATCH /{name} — update
# ---------------------------------------------------------------------------


@router.patch("/{name}")
async def update_endpoint(
    body: UpdateFirmModeBody,
    firm_id: str = Path(...),
    name: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await require_firm_member(firm_id, user, resource_kind="firm_modes")
    await require_firm_admin(firm_id, user, resource_kind="firm_modes")
    try:
        fm = await update_firm_mode(
            firm_id=firm_id,
            name=name,
            config=body.config,
            updated_by=user.get("user_id"),
            actor_email=user.get("email"),
        )
    except ModeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ModeConfigError as e:
        raise _config_error(e) from e
    return {"firm_mode": fm.to_dict()}


# ---------------------------------------------------------------------------
# POST /{name}/retire
# ---------------------------------------------------------------------------


@router.post("/{name}/retire")
async def retire_endpoint(
    firm_id: str = Path(...),
    name: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await require_firm_member(firm_id, user, resource_kind="firm_modes")
    await require_firm_admin(firm_id, user, resource_kind="firm_modes")
    try:
        fm = await retire_firm_mode(
            firm_id=firm_id,
            name=name,
            retired_by=user.get("user_id"),
            actor_email=user.get("email"),
        )
    except ModeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"firm_mode": fm.to_dict()}


# ---------------------------------------------------------------------------
# POST /{name}/restore
# ---------------------------------------------------------------------------


@router.post("/{name}/restore")
async def restore_endpoint(
    firm_id: str = Path(...),
    name: str = Path(...),
    user: dict = Depends(get_current_user),
) -> dict:
    await require_firm_member(firm_id, user, resource_kind="firm_modes")
    await require_firm_admin(firm_id, user, resource_kind="firm_modes")
    try:
        fm = await restore_firm_mode(
            firm_id=firm_id,
            name=name,
            actor_user_id=user.get("user_id"),
            actor_email=user.get("email"),
        )
    except ModeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"firm_mode": fm.to_dict()}
