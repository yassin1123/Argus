"""Phase 4 / Week 18 / Day 3 — email delivery + preferences API tests.

Nine tests per spec. Reuses the in-memory DB fake pattern from
W18/D1+D2, extended to back the delivery worker's JOIN against
users + firms.branding.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import notification_preferences as prefs_api
from auth.dependencies import get_current_user
from core.notifications import dispatcher as dispatcher_mod
from core.notifications import wiring as wiring_mod
from core.notifications.email import (
    CaptureEmailAdapter,
    EmailSendResult,
    deliver_for_ids,
    reset_adapter_for_tests,
)
from core.notifications.email import delivery as delivery_mod
from core.notifications import recipients as recipients_mod


_FIRM_ID = "11111111-1111-1111-1111-111111111111"
_SESSION_ID = "33333333-3333-3333-3333-333333333333"
_LEAD_ID = "44444444-4444-4444-4444-444444444444"
_PARTNER_ID = "66666666-6666-6666-6666-666666666666"


def _build_store() -> dict[str, Any]:
    return {
        "sessions": {
            _SESSION_ID: {
                "firm_id": _FIRM_ID,
                "title": "Kestrel Logistics",
                "review_assigned_to": _PARTNER_ID,
                "submitted_by": _LEAD_ID,
                "created_by_user_id": _LEAD_ID,
            },
        },
        "users": {
            _LEAD_ID: ("Helena Voss", "helena@meridian.invalid"),
            _PARTNER_ID: ("Sarah Kim", "sarah@meridian.invalid"),
        },
        "firms": {
            _FIRM_ID: {
                "name": "Meridian Advisory",
                "branding": {
                    "primary_color": "#1F3A5F",
                    "secondary_color": "#C97B3A",
                    "footer_text": "Meridian Advisory · Confidential",
                },
            },
        },
        "preferences": {},
        "notifications": [],
        "members": {
            (_SESSION_ID, _LEAD_ID): {"role": "lead", "removed_at": None},
        },
        "firm_memberships": {
            (_FIRM_ID, _LEAD_ID): "member",
            (_FIRM_ID, _PARTNER_ID): "member",
        },
    }


def _patch_db(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if "FROM users WHERE id" in s:
            uid = str(args[0])
            tup = store["users"].get(uid)
            if not tup:
                return None
            return {"full_name": tup[0], "email": tup[1]}
        if "FROM notification_preferences" in s and "WHERE user_id = $1::uuid AND notification_type" in s:
            uid, nt = str(args[0]), args[1]
            pref = store["preferences"].get((uid, nt))
            if pref is None:
                return None
            return {"in_app": pref[0], "email": pref[1]}
        if "INSERT INTO notifications" in s and "RETURNING" in s:
            nid = str(uuid.uuid4())
            row = {
                "id": nid,
                "recipient_id": str(args[0]),
                "firm_id": str(args[1]),
                "notification_type": args[2],
                "session_id": str(args[3]) if args[3] else None,
                "source_ref": json.loads(args[4]) if args[4] else {},
                "actor_id": str(args[5]) if args[5] else None,
                "summary": args[6],
                "read": False,
                "read_at": None,
                "created_at": datetime.now(tz=timezone.utc),
                "email_status": args[7],
            }
            store["notifications"].append(row)
            return row
        if "review_assigned_to, submitted_by, created_by_user_id" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return sess if sess else None
        if "FROM sessions WHERE id" in s and "firm_id" in s and "review_state" not in s and "title" not in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"firm_id": sess["firm_id"]} if sess else None
        if "SELECT title FROM sessions" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"title": sess["title"]} if sess else None
        if "engagement_memberships" in s and "role = 'lead'" in s and "LIMIT 1" in s:
            sid = str(args[0])
            for (s_id, u_id), m in store["members"].items():
                if s_id == sid and m["role"] == "lead" and m["removed_at"] is None:
                    return {"user_id": u_id}
            return None
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        # delivery._fetch_pending — joins users + firms
        if "FROM notifications n" in s and "JOIN users u" in s and "JOIN firms f" in s:
            target_ids: list[str] | None = None
            if "n.id = ANY" in s:
                target_ids = [str(x) for x in args[0]]
            rows = []
            for n in store["notifications"]:
                if n["email_status"] != "pending":
                    continue
                if target_ids is not None and n["id"] not in target_ids:
                    continue
                u = store["users"].get(n["recipient_id"])
                f = store["firms"].get(n["firm_id"])
                if not u or not f:
                    continue
                rows.append({
                    **n,
                    "recipient_email": u[1],
                    "recipient_name": u[0],
                    "firm_name": f["name"],
                    "firm_branding": f["branding"],
                })
            return rows
        # prefs GET
        if "FROM notification_preferences" in s and "WHERE user_id = $1::uuid" in s:
            uid = str(args[0])
            return [
                {"notification_type": nt, "in_app": v[0], "email": v[1]}
                for (u, nt), v in store["preferences"].items()
                if u == uid
            ]
        # Comments fetch (mentions / thread)
        if "FROM comments" in s and "id = $1::uuid OR parent_comment_id" in s:
            return []
        return []

    async def execute(sql: str, *args: Any) -> str:
        s = " ".join(sql.split())
        if "UPDATE notifications" in s and "SET email_status" in s:
            nid, status = str(args[0]), args[1]
            for n in store["notifications"]:
                if n["id"] == nid:
                    n["email_status"] = status
                    break
            return "UPDATE 1"
        if "INSERT INTO notification_preferences" in s:
            uid, nt, in_app, email = str(args[0]), args[1], args[2], args[3]
            store["preferences"][(uid, nt)] = (bool(in_app), bool(email))
            return "INSERT 0 1"
        if "DELETE FROM notification_preferences" in s:
            uid = str(args[0])
            keys = [k for k in store["preferences"] if k[0] == uid]
            for k in keys:
                del store["preferences"][k]
            return f"DELETE {len(keys)}"
        return "UPDATE 0"

    async def fetchval(sql: str, *args: Any) -> Any:
        return None

    fake_conn = mock.MagicMock()
    fake_conn.fetchrow = fetchrow
    fake_conn.fetch = fetch
    fake_conn.execute = execute
    fake_conn.fetchval = fetchval

    class _AcquireCM:
        async def __aenter__(self):
            return fake_conn
        async def __aexit__(self, *a):
            return None

    def _acquire():
        return _AcquireCM()

    monkeypatch.setattr(dispatcher_mod, "acquire", _acquire)
    monkeypatch.setattr(recipients_mod, "acquire", _acquire)
    monkeypatch.setattr(wiring_mod, "acquire", _acquire)
    monkeypatch.setattr(delivery_mod, "acquire", _acquire)
    monkeypatch.setattr(prefs_api, "acquire", _acquire)


def _fresh_capture(monkeypatch: pytest.MonkeyPatch) -> CaptureEmailAdapter:
    """Reset the process-wide adapter to a clean capture instance."""
    adapter = CaptureEmailAdapter()
    reset_adapter_for_tests(adapter)
    return adapter


# ---------------------------------------------------------------------------
# 1. Capture adapter records a notification email end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_adapter_records_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    capture = _fresh_capture(monkeypatch)

    from core.notifications.wiring import notify_comment_created
    out = await notify_comment_created(
        session_id=uuid.UUID(_SESSION_ID), firm_id=uuid.UUID(_FIRM_ID),
        author_id=uuid.UUID(_LEAD_ID),
        comment_id="c-1", body="Heads up @sarah look here.",
        anchor_ref={}, mentioned_user_ids=[_PARTNER_ID],
    )
    assert out and out[0].recipient_id == _PARTNER_ID
    assert len(capture.captured) == 1
    cap = capture.captured[0]
    assert cap.to_email == "sarah@meridian.invalid"
    assert "mentioned" in cap.subject.lower()
    # Notification row was flipped from pending → sent.
    notif = next(n for n in store["notifications"] if n["id"] == out[0].id)
    assert notif["email_status"] == "sent"


# ---------------------------------------------------------------------------
# 2. Email pref disabled → email_status='skipped', capture empty
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_not_sent_when_preference_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    # Partner opts out of mention emails.
    store["preferences"][(_PARTNER_ID, "mention")] = (True, False)
    capture = _fresh_capture(monkeypatch)

    from core.notifications.wiring import notify_comment_created
    out = await notify_comment_created(
        session_id=uuid.UUID(_SESSION_ID), firm_id=uuid.UUID(_FIRM_ID),
        author_id=uuid.UUID(_LEAD_ID),
        comment_id="c-1", body="@sarah heads up", anchor_ref={},
        mentioned_user_ids=[_PARTNER_ID],
    )
    assert out and out[0].email_status == "skipped"
    assert capture.captured == []


# ---------------------------------------------------------------------------
# 3. Email rendered with firm branding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_rendered_with_firm_branding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    capture = _fresh_capture(monkeypatch)

    from core.notifications.wiring import notify_comment_created
    await notify_comment_created(
        session_id=uuid.UUID(_SESSION_ID), firm_id=uuid.UUID(_FIRM_ID),
        author_id=uuid.UUID(_LEAD_ID),
        comment_id="c-1", body="@sarah look here",
        anchor_ref={}, mentioned_user_ids=[_PARTNER_ID],
    )
    assert len(capture.captured) == 1
    html = capture.captured[0].html_body
    # Branding fields land in the HTML.
    assert "#1F3A5F" in html
    assert "Meridian Advisory" in html
    assert "Confidential" in html


# ---------------------------------------------------------------------------
# 4. Email includes the View-in-Argus link to the right session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_includes_view_in_argus_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    monkeypatch.setenv("ARGUS_BASE_URL", "https://argus.example.com")
    capture = _fresh_capture(monkeypatch)

    from core.notifications.wiring import notify_comment_created
    await notify_comment_created(
        session_id=uuid.UUID(_SESSION_ID), firm_id=uuid.UUID(_FIRM_ID),
        author_id=uuid.UUID(_LEAD_ID),
        comment_id="c-42", body="@sarah",
        anchor_ref={}, mentioned_user_ids=[_PARTNER_ID],
    )
    cap = capture.captured[0]
    expected = f"https://argus.example.com/sessions/{_SESSION_ID}#comment-c-42"
    assert expected in cap.html_body
    assert expected in cap.text_body
    assert 'data-testid="view-in-argus"' in cap.html_body


# ---------------------------------------------------------------------------
# 5. Delivery idempotent — running twice doesn't double-send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    capture = _fresh_capture(monkeypatch)

    # Seed a pending notification directly.
    nid = str(uuid.uuid4())
    store["notifications"].append({
        "id": nid, "recipient_id": _PARTNER_ID, "firm_id": _FIRM_ID,
        "notification_type": "mention",
        "session_id": _SESSION_ID, "source_ref": {"comment_id": "c-1"},
        "actor_id": _LEAD_ID, "summary": "Marcus mentioned you on Kestrel",
        "read": False, "read_at": None,
        "created_at": datetime.now(tz=timezone.utc),
        "email_status": "pending",
    })

    report1 = await deliver_for_ids([nid])
    assert report1.sent == 1
    assert len(capture.captured) == 1
    # Second run picks no rows (status is now 'sent').
    report2 = await deliver_for_ids([nid])
    assert report2.sent == 0
    assert report2.attempted == 0
    assert len(capture.captured) == 1


# ---------------------------------------------------------------------------
# 6. Adapter error flips row → email_status='failed'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_marks_failed_on_adapter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    class BoomAdapter:
        transport = "boom"
        async def send(self, **kwargs: Any) -> EmailSendResult:
            return EmailSendResult(
                ok=False, transport=self.transport,
                reason="simulated transport error",
            )

    reset_adapter_for_tests(BoomAdapter())  # type: ignore[arg-type]

    nid = str(uuid.uuid4())
    store["notifications"].append({
        "id": nid, "recipient_id": _PARTNER_ID, "firm_id": _FIRM_ID,
        "notification_type": "mention",
        "session_id": _SESSION_ID, "source_ref": {"comment_id": "c-1"},
        "actor_id": _LEAD_ID, "summary": "Marcus mentioned you on Kestrel",
        "read": False, "read_at": None,
        "created_at": datetime.now(tz=timezone.utc),
        "email_status": "pending",
    })

    report = await deliver_for_ids([nid])
    assert report.failed == 1
    flipped = next(n for n in store["notifications"] if n["id"] == nid)
    assert flipped["email_status"] == "failed"


# ---------------------------------------------------------------------------
# 7-9. Preferences API (GET / PUT / RESET)
# ---------------------------------------------------------------------------


def _build_app(user_id: str) -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.include_router(prefs_api.router, prefix="/api")

    async def fake_user() -> dict:
        return {"user_id": user_id, "email": f"{user_id}@m.invalid", "role": "member"}

    app.dependency_overrides[get_current_user] = fake_user
    return app, TestClient(app)


def test_preferences_get_fills_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_LEAD_ID)

    resp = client.get("/api/me/notification-preferences")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = {p["notification_type"]: p for p in body["preferences"]}
    # Every NotificationType is present.
    from core.notifications.types import NotificationType
    for nt in NotificationType:
        assert nt.value in types
        # Source is 'default' because no rows have been written.
        assert types[nt.value]["source"] == "default"
    # MENTION default = (True, True).
    assert types["mention"]["in_app"] is True
    assert types["mention"]["email"] is True
    # SECTION_ASSIGNED default = (True, False).
    assert types["section_assigned"]["email"] is False


def test_preferences_update_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_LEAD_ID)

    resp = client.put(
        "/api/me/notification-preferences",
        json={"preferences": [
            {"notification_type": "mention", "in_app": True, "email": False},
            {"notification_type": "comment_reply", "in_app": False, "email": False},
        ]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = {p["notification_type"]: p for p in body["preferences"]}
    assert types["mention"]["email"] is False
    assert types["mention"]["source"] == "stored"
    assert types["comment_reply"]["in_app"] is False
    # Persisted in store too.
    assert store["preferences"][(_LEAD_ID, "mention")] == (True, False)


def test_preferences_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    # Seed a custom pref.
    store["preferences"][(_LEAD_ID, "mention")] = (True, False)
    _, client = _build_app(_LEAD_ID)

    resp = client.post("/api/me/notification-preferences/reset")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Custom pref wiped.
    assert all(k[0] != _LEAD_ID for k in store["preferences"])
    # Returned shape falls back to defaults for every type.
    types = {p["notification_type"]: p for p in body["preferences"]}
    assert types["mention"]["source"] == "default"
    assert types["mention"]["email"] is True
