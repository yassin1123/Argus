"""Notification preferences API — Phase 4 / Week 18 / Day 3.

Three endpoints, all self-only (mounted under ``/api/me``):

  GET   /api/me/notification-preferences          fill defaults for
                                                   types the user
                                                   hasn't customised
  PUT   /api/me/notification-preferences          upsert one or many
                                                   per-type prefs
  POST  /api/me/notification-preferences/reset    delete every row;
                                                   future reads fall
                                                   back to defaults

The shape returned + accepted is a list of
``{notification_type, in_app, email}`` entries — one per
``NotificationType``. The dispatcher reads
``notification_preferences`` first and falls back to
:func:`default_preference` when no row exists, so users without
any rows still get sensible behaviour.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from core.notifications.defaults import default_preference
from core.notifications.types import NotificationType
from db.connection import acquire

logger = logging.getLogger(__name__)

router = APIRouter()


class PreferenceEntry(BaseModel):
    """One row's worth — used in both GET response + PUT body."""

    notification_type: str = Field(..., min_length=1, max_length=32)
    in_app: bool
    email: bool

    model_config = {"extra": "ignore"}


class UpdatePreferencesBody(BaseModel):
    """PUT body: any number of per-type prefs upserted in one call."""

    preferences: list[PreferenceEntry] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _load_user_preferences(user_id: UUID) -> dict[str, tuple[bool, bool]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT notification_type, in_app, email
              FROM notification_preferences
             WHERE user_id = $1::uuid
            """,
            user_id,
        )
    return {
        str(r["notification_type"]): (bool(r["in_app"]), bool(r["email"]))
        for r in rows
    }


async def _upsert_preference(
    user_id: UUID, notification_type: str, in_app: bool, email: bool,
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO notification_preferences
                (user_id, notification_type, in_app, email)
            VALUES ($1::uuid, $2, $3, $4)
            ON CONFLICT (user_id, notification_type) DO UPDATE
              SET in_app = EXCLUDED.in_app,
                  email = EXCLUDED.email
            """,
            user_id, notification_type, in_app, email,
        )


async def _delete_all_preferences(user_id: UUID) -> int:
    async with acquire() as conn:
        result = await conn.execute(
            "DELETE FROM notification_preferences WHERE user_id = $1::uuid",
            user_id,
        )
    try:
        return int(result.split()[-1])
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _full_preference_list(
    stored: dict[str, tuple[bool, bool]],
) -> list[dict[str, Any]]:
    """One entry per :class:`NotificationType`, using stored rows
    when present and :func:`default_preference` when not. The full
    list lets the frontend render a static settings panel without
    having to know which types are 'new'."""
    out: list[dict[str, Any]] = []
    for nt in NotificationType:
        if nt.value in stored:
            in_app, email = stored[nt.value]
            source = "stored"
        else:
            in_app, email = default_preference(nt)
            source = "default"
        out.append({
            "notification_type": nt.value,
            "in_app": in_app,
            "email": email,
            "source": source,
        })
    return out


def _parse_user_id(user: dict) -> UUID:
    try:
        return UUID(str(user["user_id"]))
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid user_id: {e}") from e


@router.get("/me/notification-preferences")
async def get_preferences_endpoint(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    uid = _parse_user_id(user)
    stored = await _load_user_preferences(uid)
    return {
        "user_id": str(uid),
        "preferences": _full_preference_list(stored),
    }


@router.put("/me/notification-preferences")
async def update_preferences_endpoint(
    body: UpdatePreferencesBody,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    uid = _parse_user_id(user)
    # Validate notification_type values up front so a typo in one
    # entry doesn't half-persist the rest.
    for entry in body.preferences:
        try:
            NotificationType(entry.notification_type)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"unknown notification_type: {entry.notification_type!r}",
            ) from e
    for entry in body.preferences:
        await _upsert_preference(
            uid, entry.notification_type, entry.in_app, entry.email,
        )
    stored = await _load_user_preferences(uid)
    return {
        "user_id": str(uid),
        "preferences": _full_preference_list(stored),
        "updated": len(body.preferences),
    }


@router.post("/me/notification-preferences/reset")
async def reset_preferences_endpoint(
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    uid = _parse_user_id(user)
    deleted = await _delete_all_preferences(uid)
    return {
        "user_id": str(uid),
        "deleted": deleted,
        "preferences": _full_preference_list({}),
    }


__all__ = ["router"]
