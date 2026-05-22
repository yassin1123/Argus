"""Phase 2 / Week 9 / Day 4 — permissions on the deepening API.

Spec rule: deepening is firm_member. Non-members return 404
(session hidden); read-only members return 403; write-tier members
can deepen.

Tests use FastAPI's TestClient with the auth dependency overridden
so we can inject a fake user without spinning up Postgres.
"""

from __future__ import annotations

from unittest import mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import section_deepening as sd_module
from auth.dependencies import get_current_user


def _build_app(user_id: str | None = None) -> tuple[FastAPI, TestClient]:
    # The endpoint coerces ``user["user_id"]`` to a UUID, so the
    # fake user needs a real UUID string.
    uid = user_id or str(uuid4())
    app = FastAPI()
    app.include_router(sd_module.router, prefix="/api/sessions")

    async def fake_user() -> dict:
        return {"user_id": uid, "email": "demo@argus.local", "role": "member"}

    app.dependency_overrides[get_current_user] = fake_user
    return app, TestClient(app)


def test_member_can_deepen_returns_queued() -> None:
    sid = str(uuid4())
    app, client = _build_app()
    # W15/D2 added an ``auto_revert_if_locked`` call before the
    # background-task dispatch — mock it to return None (no revert
    # needed) so the existing permission test stays focused on the
    # auth path, not the new lock-check path.
    with mock.patch.object(sd_module, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(sd_module, "can_write", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(sd_module, "auto_revert_if_locked", new=mock.AsyncMock(return_value=None)):
        r = client.post(
            f"/api/sessions/{sid}/deepen",
            json={"section_path": "summary", "depth_directive": "Tighten."},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["section_path"] == "summary"
    # When no revert fired, the response stays at the W9/D4 shape — no
    # review_auto_reverted flag.
    assert "review_auto_reverted" not in body


def test_non_member_gets_404_not_403() -> None:
    """Spec hard rule: non-members must not be able to tell whether
    the session exists — they get 404 (Session not found), not 403
    (Write access required)."""
    sid = str(uuid4())
    app, client = _build_app()
    with mock.patch.object(sd_module, "can_read", new=mock.AsyncMock(return_value=False)), \
         mock.patch.object(sd_module, "can_write", new=mock.AsyncMock(return_value=False)):
        r = client.post(
            f"/api/sessions/{sid}/deepen",
            json={"section_path": "summary"},
        )
    assert r.status_code == 404, r.text
    assert "Session not found" in r.json()["detail"]


def test_read_only_member_gets_403() -> None:
    """A firm member who can read the session but not write to it
    gets 403 on POST (deepening costs LLM budget — write-tier
    only)."""
    sid = str(uuid4())
    app, client = _build_app()
    with mock.patch.object(sd_module, "can_read", new=mock.AsyncMock(return_value=True)), \
         mock.patch.object(sd_module, "can_write", new=mock.AsyncMock(return_value=False)):
        r = client.post(
            f"/api/sessions/{sid}/deepen",
            json={"section_path": "summary"},
        )
    assert r.status_code == 403, r.text


def test_non_member_get_detail_returns_404() -> None:
    """The same hiding rule applies to the detail endpoint."""
    sid = str(uuid4())
    did = str(uuid4())
    app, client = _build_app()
    with mock.patch.object(sd_module, "can_read", new=mock.AsyncMock(return_value=False)):
        r = client.get(f"/api/sessions/{sid}/deepen/{did}")
    assert r.status_code == 404, r.text


def test_accept_non_member_404() -> None:
    sid = str(uuid4())
    did = str(uuid4())
    app, client = _build_app()
    with mock.patch.object(sd_module, "can_read", new=mock.AsyncMock(return_value=False)), \
         mock.patch.object(sd_module, "can_write", new=mock.AsyncMock(return_value=False)):
        r = client.post(f"/api/sessions/{sid}/deepen/{did}/accept")
    assert r.status_code == 404


def test_reject_non_member_404() -> None:
    sid = str(uuid4())
    did = str(uuid4())
    app, client = _build_app()
    with mock.patch.object(sd_module, "can_read", new=mock.AsyncMock(return_value=False)), \
         mock.patch.object(sd_module, "can_write", new=mock.AsyncMock(return_value=False)):
        r = client.post(f"/api/sessions/{sid}/deepen/{did}/reject")
    assert r.status_code == 404
