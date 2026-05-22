"""Phase 4 / Week 16 / Day 2 — comment API + threading + mentions tests.

Eleven tests per spec. The harness mirrors W16/D1
(``test_comments_service.py``) but extends the in-memory DB fake
with the W16/D2 surfaces:

  - Thread assembly queries (root + replies ordering).
  - Firm-member listing for mention parsing.
  - audit_events INSERT so we can assert every action logs.
  - Counts per anchor / section.
  - The W15 review-state read that's now augmented with a
    ``comments`` block.

All API tests go through ``TestClient`` with the
``get_current_user`` dependency overridden so we avoid baking JWT
machinery into the tests. The auth gate
(:func:`auth.permissions.can_read`) is monkey-patched per-test:
True for the engagement-firm callers, False for the cross-firm
test.
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

from api import comments as comments_api
from api import review as review_api
from auth.dependencies import get_current_user


# ---------------------------------------------------------------------------
# Stable IDs (shared between the seed + every assertion in this module)
# ---------------------------------------------------------------------------


_FIRM_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_FIRM_ID = "22222222-2222-2222-2222-222222222222"
_SESSION_ID = "33333333-3333-3333-3333-333333333333"
_AUTHOR_ID = "44444444-4444-4444-4444-444444444444"
_PARTNER_ID = "55555555-5555-5555-5555-555555555555"
_ADMIN_ID = "66666666-6666-6666-6666-666666666666"
_OUTSIDER_ID = "77777777-7777-7777-7777-777777777777"


# ---------------------------------------------------------------------------
# In-memory DB fake (extends the W16/D1 pattern)
# ---------------------------------------------------------------------------


def _build_store() -> dict[str, Any]:
    """Plant a session with synergy_estimate + claim_kgr_1, two firm
    members (author + partner) for mention parsing, one admin."""
    return {
        "comments": {},      # id -> row
        "audit_events": [],  # list of dicts
        "sessions": {
            _SESSION_ID: {
                "firm_id": _FIRM_ID,
                "payload": {
                    "recommendation": "PROCEED",
                    "summary": "Synergy basis carries the recommendation.",
                    "key_reasons": [
                        {"text": "Resilient gross margin", "claim_id": "claim_kgr_1"},
                    ],
                    "risks": [], "counterarguments": [], "next_steps": [],
                    "sources": [], "caveats": "",
                    "confidence_level": "Medium",
                    "consulting_payload": {
                        "synergy_estimate": {
                            "revenue_synergies": [
                                {"type": "Cross-sell", "magnitude_gbp_m": 5.0,
                                 "basis_citations": ["claim_kgr_1"]},
                            ],
                            "cost_synergies": [],
                        },
                        "recommendation_claim_ids": ["claim_kgr_1"],
                    },
                },
                "artifacts": [],
            },
        },
        # firm_id -> list[{user_id, email, full_name, created_at}]
        "firm_members": {
            _FIRM_ID: [
                {"user_id": _AUTHOR_ID, "email": "alex.chen@meridian.invalid",
                 "full_name": "Alex Chen",
                 "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
                {"user_id": _PARTNER_ID, "email": "sarah.kim@meridian.invalid",
                 "full_name": "Sarah Kim",
                 "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc)},
                {"user_id": _ADMIN_ID, "email": "kira.lee@meridian.invalid",
                 "full_name": "Kira Lee",
                 "created_at": datetime(2026, 1, 3, tzinfo=timezone.utc)},
            ],
        },
        # (firm_id, user_id) -> role (used by service-layer admin check)
        "memberships": {
            (_FIRM_ID, _AUTHOR_ID): "member",
            (_FIRM_ID, _PARTNER_ID): "member",
            (_FIRM_ID, _ADMIN_ID): "admin",
        },
    }


def _patch_db(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    """Install the in-memory DB fake across every module that
    imports :func:`acquire`. Each module gets its own monkeypatched
    attribute (because the symbol was imported at module-load via
    ``from db.connection import acquire``)."""

    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if "FROM sessions WHERE id" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            if sess is None:
                return None
            # The api/comments _load_comment_session uses a different SELECT;
            # this matches the service's firm-id-only lookup too.
            return {"firm_id": sess["firm_id"], "metadata": None}
        if "FROM reports WHERE session_id" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            if sess is None:
                return None
            p = sess.get("payload") or {}
            return {
                "recommendation": p.get("recommendation"),
                "confidence_level": p.get("confidence_level"),
                "summary": p.get("summary"),
                "key_reasons": p.get("key_reasons"),
                "risks": p.get("risks"),
                "counterarguments": p.get("counterarguments"),
                "next_steps": p.get("next_steps"),
                "sources": p.get("sources"),
                "caveats": p.get("caveats"),
                "consulting_payload": p.get("consulting_payload", {}),
            }
        if "FROM comments WHERE id" in s:
            cid = str(args[0])
            row = store["comments"].get(cid)
            if row:
                # api/comments._load_comment_session selects three fields;
                # service._load_comment selects everything. Same row works.
                return row
            return None
        if "FROM firm_memberships" in s:
            firm_id, user_id = str(args[0]), str(args[1])
            role = store["memberships"].get((firm_id, user_id))
            return {"role": role} if role else None
        if "INSERT INTO comments" in s and "RETURNING" in s:
            new_id = str(uuid.uuid4())
            now = datetime.now(tz=timezone.utc)
            session_id = str(args[0])
            firm_id = str(args[1])
            if len(args) == 8:
                parent_id = args[2]
                anchor_type = args[3]
                anchor_ref_json = args[4]
                body = args[5]
                mentions_json = args[6]
                author_id = str(args[7])
            else:
                parent_id = None
                anchor_type = args[2]
                anchor_ref_json = args[3]
                body = args[4]
                mentions_json = args[5]
                author_id = str(args[6])
            row = {
                "id": new_id,
                "session_id": session_id,
                "firm_id": firm_id,
                "parent_comment_id": str(parent_id) if parent_id else None,
                "anchor_type": anchor_type,
                "anchor_ref": json.loads(anchor_ref_json or "{}"),
                "body": body,
                "mentioned_user_ids": json.loads(mentions_json or "[]"),
                "author_id": author_id,
                "resolved": False,
                "resolved_by": None,
                "resolved_at": None,
                "created_at": now,
                "updated_at": now,
                "edited_at": None,
                "deleted_at": None,
            }
            store["comments"][new_id] = row
            return row
        if "UPDATE comments" in s and "RETURNING" in s:
            cid = str(args[0])
            row = store["comments"].get(cid)
            if not row:
                return None
            row["body"] = args[1]
            row["edited_at"] = datetime.now(tz=timezone.utc)
            row["updated_at"] = datetime.now(tz=timezone.utc)
            return row
        # threads.count_unresolved_for_session
        if "FILTER (WHERE resolved = FALSE)" in s:
            sid = str(args[0])
            rows = [
                r for r in store["comments"].values()
                if r["session_id"] == sid
                and r["parent_comment_id"] is None
                and r["deleted_at"] is None
            ]
            return {
                "unresolved": sum(1 for r in rows if not r["resolved"]),
                "total": len(rows),
            }
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        if "FROM export_artifacts" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return sess.get("artifacts", []) if sess else []
        if "FROM comments" in s:
            # get_threads_for_session — supports the WHERE/ORDER shape
            # we emit. Re-parse the WHERE from args.
            sid = str(args[0])
            anchor_type_filter = args[1] if len(args) >= 2 else None
            rows = [
                r for r in store["comments"].values()
                if r["session_id"] == sid and r["deleted_at"] is None
            ]
            if anchor_type_filter is not None:
                rows = [r for r in rows if r["anchor_type"] == anchor_type_filter]
            rows.sort(key=lambda r: (r["created_at"], r["id"]))
            return rows
        if "FROM firm_memberships" in s and "JOIN users" in s:
            firm_id = str(args[0])
            members = store["firm_members"].get(firm_id, [])
            return [
                {
                    "user_id": uuid.UUID(m["user_id"]),
                    "email": m["email"],
                    "full_name": m["full_name"],
                    "created_at": m["created_at"],
                }
                for m in members
            ]
        return []

    async def fetchval(sql: str, *args: Any) -> Any:
        return None

    async def execute(sql: str, *args: Any) -> None:
        s = " ".join(sql.split())
        if "INSERT INTO audit_events" in s:
            # Match queries.append_event positional args.
            store["audit_events"].append({
                "actor_user_id": args[0],
                "actor_email": args[1],
                "action": args[2],
                "resource_type": args[3],
                "resource_id": args[4],
                "method": args[5] if len(args) > 5 else None,
                "path": args[6] if len(args) > 6 else None,
                "status_code": args[7] if len(args) > 7 else None,
                "ip": args[8] if len(args) > 8 else None,
                "user_agent": args[9] if len(args) > 9 else None,
                "payload": json.loads(args[10]) if len(args) > 10 and args[10] else {},
            })
            return
        if "UPDATE comments" in s and "deleted_at = NOW()" in s:
            cid = str(args[0])
            row = store["comments"].get(cid)
            if row:
                row["deleted_at"] = datetime.now(tz=timezone.utc)
                row["updated_at"] = datetime.now(tz=timezone.utc)
            return
        if "UPDATE comments" in s and "resolved = TRUE" in s:
            cid = str(args[0])
            actor = str(args[1])
            row = store["comments"].get(cid)
            if row:
                row["resolved"] = True
                row["resolved_by"] = actor
                row["resolved_at"] = datetime.now(tz=timezone.utc)
                row["updated_at"] = datetime.now(tz=timezone.utc)
            return
        if "UPDATE comments" in s and "resolved = FALSE" in s:
            cid = str(args[0])
            row = store["comments"].get(cid)
            if row:
                row["resolved"] = False
                row["resolved_by"] = None
                row["resolved_at"] = None
                row["updated_at"] = datetime.now(tz=timezone.utc)
            return

    fake_conn = mock.MagicMock()
    fake_conn.fetchrow = fetchrow
    fake_conn.fetch = fetch
    fake_conn.fetchval = fetchval
    fake_conn.execute = execute

    class _AcquireCM:
        async def __aenter__(self):
            return fake_conn
        async def __aexit__(self, *a):
            return None

    def _acquire():
        return _AcquireCM()

    # Patch acquire on every module that does ``from db.connection
    # import acquire`` — Python binds the symbol at import time, so a
    # plain monkeypatch on db.connection.acquire wouldn't reach them.
    import api.comments as _api_comments
    import audit.queries as _audit_queries
    import core.comments.service as _svc
    import core.comments.threads as _threads
    monkeypatch.setattr(_api_comments, "acquire", _acquire)
    monkeypatch.setattr(_audit_queries, "acquire", _acquire)
    monkeypatch.setattr(_svc, "acquire", _acquire)
    monkeypatch.setattr(_threads, "acquire", _acquire)


# ---------------------------------------------------------------------------
# App + auth wiring
# ---------------------------------------------------------------------------


def _build_app(
    user_id: str,
    *,
    can_read: bool = True,
) -> tuple[FastAPI, TestClient]:
    """Spin up a TestClient with the comments router + a fake
    ``get_current_user`` + a patched ``can_read``."""
    app = FastAPI()
    app.include_router(comments_api.router, prefix="/api")
    app.include_router(review_api.router, prefix="/api/sessions")

    async def fake_user() -> dict:
        return {"user_id": user_id, "email": f"{user_id}@meridian.invalid",
                "role": "member"}

    async def fake_can_read(_engagement_id: str, _user: dict) -> bool:
        return can_read

    app.dependency_overrides[get_current_user] = fake_user
    # Patch the can_read symbol both routers import; the dependency
    # override doesn't reach module-level imports.
    import api.comments as _api_comments
    import api.review as _api_review
    _api_comments.can_read = fake_can_read  # type: ignore[assignment]
    _api_review.can_read = fake_can_read  # type: ignore[assignment]
    return app, TestClient(app)


# ---------------------------------------------------------------------------
# Test 1 — create + retrieve thread
# ---------------------------------------------------------------------------


def test_create_and_retrieve_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    create_resp = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={
            "anchor_type": "section",
            "anchor_ref": {"section_path": "synergy_estimate"},
            "body": "Tighten the synergy basis.",
        },
    )
    assert create_resp.status_code == 200, create_resp.text
    comment_id = create_resp.json()["id"]

    list_resp = client.get(f"/api/sessions/{_SESSION_ID}/comments")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] == 1
    assert body["threads"][0]["root"]["id"] == comment_id
    assert body["threads"][0]["replies"] == []
    assert body["threads"][0]["resolved"] is False


# ---------------------------------------------------------------------------
# Test 2 — reply appears in thread
# ---------------------------------------------------------------------------


def test_reply_appears_in_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    root = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {}, "body": "Overall fine."},
    ).json()
    reply_resp = client.post(
        f"/api/comments/{root['id']}/replies",
        json={"body": "Agreed, two small follow-ups."},
    )
    assert reply_resp.status_code == 200, reply_resp.text
    reply = reply_resp.json()
    assert reply["parent_comment_id"] == root["id"]
    assert reply["anchor_type"] == "engagement"  # inherited

    threads = client.get(f"/api/sessions/{_SESSION_ID}/comments").json()["threads"]
    assert len(threads) == 1
    assert len(threads[0]["replies"]) == 1
    assert threads[0]["replies"][0]["id"] == reply["id"]


# ---------------------------------------------------------------------------
# Test 3 — threads grouped correctly
# ---------------------------------------------------------------------------


def test_threads_grouped_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    r1 = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {}, "body": "Root 1"},
    ).json()
    r2 = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {}, "body": "Root 2"},
    ).json()
    client.post(f"/api/comments/{r1['id']}/replies",
                json={"body": "Reply on r1 #1"})
    client.post(f"/api/comments/{r1['id']}/replies",
                json={"body": "Reply on r1 #2"})
    client.post(f"/api/comments/{r2['id']}/replies",
                json={"body": "Reply on r2"})

    threads = client.get(f"/api/sessions/{_SESSION_ID}/comments").json()["threads"]
    assert len(threads) == 2
    by_id = {t["root"]["id"]: t for t in threads}
    assert len(by_id[r1["id"]]["replies"]) == 2
    assert len(by_id[r2["id"]]["replies"]) == 1


# ---------------------------------------------------------------------------
# Test 4 — filter by anchor_type
# ---------------------------------------------------------------------------


def test_filter_by_anchor_type(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "section",
              "anchor_ref": {"section_path": "synergy_estimate"},
              "body": "Section comment"},
    )
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "claim",
              "anchor_ref": {"claim_id": "claim_kgr_1"},
              "body": "Claim comment"},
    )
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {},
              "body": "Engagement comment"},
    )

    section_only = client.get(
        f"/api/sessions/{_SESSION_ID}/comments?anchor_type=section"
    ).json()
    assert section_only["total"] == 1
    assert section_only["threads"][0]["root"]["anchor_type"] == "section"

    claim_only = client.get(
        f"/api/sessions/{_SESSION_ID}/comments?anchor_type=claim"
    ).json()
    assert claim_only["total"] == 1
    assert claim_only["threads"][0]["root"]["anchor_type"] == "claim"


# ---------------------------------------------------------------------------
# Test 5 — filter by resolved status
# ---------------------------------------------------------------------------


def test_filter_by_resolved_status(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    c1 = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {}, "body": "Will close"},
    ).json()
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {}, "body": "Stays open"},
    )
    client.post(f"/api/comments/{c1['id']}/resolve")

    open_only = client.get(
        f"/api/sessions/{_SESSION_ID}/comments?resolved=false"
    ).json()
    closed_only = client.get(
        f"/api/sessions/{_SESSION_ID}/comments?resolved=true"
    ).json()
    assert open_only["total"] == 1
    assert closed_only["total"] == 1
    assert closed_only["threads"][0]["root"]["id"] == c1["id"]
    assert closed_only["threads"][0]["resolved"] is True


# ---------------------------------------------------------------------------
# Test 6 — mention parsed + stored
# ---------------------------------------------------------------------------


def test_mention_parsed_and_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    resp = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={
            "anchor_type": "section",
            "anchor_ref": {"section_path": "synergy_estimate"},
            "body": "Hey @sarah.kim, can you check this number?",
        },
    )
    assert resp.status_code == 200
    row = resp.json()
    assert _PARTNER_ID in row["mentioned_user_ids"]
    # And a comment.mention audit event was emitted for the partner.
    mention_events = [
        e for e in store["audit_events"] if e["action"] == "comment.mention"
    ]
    assert any(
        e["payload"].get("mentioned_user_id") == _PARTNER_ID for e in mention_events
    )


# ---------------------------------------------------------------------------
# Test 7 — @-token for non-firm-member is ignored
# ---------------------------------------------------------------------------


def test_mention_non_member_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    resp = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={
            "anchor_type": "engagement",
            "anchor_ref": {},
            "body": "Hey @some.outsider and @also.unknown, FYI.",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["mentioned_user_ids"] == []
    # No comment.mention event fires for unresolved tokens.
    assert not any(
        e["action"] == "comment.mention" for e in store["audit_events"]
    )


# ---------------------------------------------------------------------------
# Test 8 — comment counts by section
# ---------------------------------------------------------------------------


def test_comment_count_by_section(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "section",
              "anchor_ref": {"section_path": "synergy_estimate"},
              "body": "On synergy 1"},
    )
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "section",
              "anchor_ref": {"section_path": "synergy_estimate"},
              "body": "On synergy 2"},
    )
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "claim",
              "anchor_ref": {"claim_id": "claim_kgr_1"},
              "body": "On claim"},
    )

    counts = client.get(f"/api/sessions/{_SESSION_ID}/comments/count").json()
    assert counts["total"] == 3
    assert counts["unresolved_total"] == 3
    assert counts["by_anchor_type"]["section"] == 2
    assert counts["by_anchor_type"]["claim"] == 1
    assert counts["by_section_path"]["synergy_estimate"] == 2


# ---------------------------------------------------------------------------
# Test 9 — cross-firm comment access returns 404
# ---------------------------------------------------------------------------


def test_cross_firm_comment_access_404(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_OUTSIDER_ID, can_read=False)

    # Cross-firm caller can't list…
    list_resp = client.get(f"/api/sessions/{_SESSION_ID}/comments")
    assert list_resp.status_code == 404

    # …can't count…
    count_resp = client.get(f"/api/sessions/{_SESSION_ID}/comments/count")
    assert count_resp.status_code == 404

    # …and can't post.
    create_resp = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {}, "body": "Sneaky."},
    )
    assert create_resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 10 — every comment action audit-logs
# ---------------------------------------------------------------------------


def test_every_comment_action_audit_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    root = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {}, "body": "Root"},
    ).json()
    reply = client.post(
        f"/api/comments/{root['id']}/replies", json={"body": "Reply"},
    ).json()
    client.patch(f"/api/comments/{root['id']}", json={"body": "Root (edited)"})
    client.post(f"/api/comments/{root['id']}/resolve")
    client.post(f"/api/comments/{root['id']}/unresolve")
    client.delete(f"/api/comments/{reply['id']}")

    actions = [e["action"] for e in store["audit_events"]]
    for needed in (
        "comment.created", "comment.replied", "comment.edited",
        "comment.resolved", "comment.unresolved", "comment.deleted",
    ):
        assert needed in actions, f"missing audit action: {needed}"


# ---------------------------------------------------------------------------
# Test 11 — review GET response carries the unresolved comment block
# ---------------------------------------------------------------------------


def test_review_response_includes_unresolved_comment_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Seed two roots (one resolved) + one reply (replies don't count).
    _, client = _build_app(_AUTHOR_ID)
    open_root = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {}, "body": "open"},
    ).json()
    closed_root = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {}, "body": "to close"},
    ).json()
    client.post(f"/api/comments/{open_root['id']}/replies", json={"body": "reply"})
    client.post(f"/api/comments/{closed_root['id']}/resolve")

    # Stub get_review_state to keep this test laser-focused on the
    # comments block injection. The real get_review_state hits sessions
    # + review_records, which is W15 territory.
    async def fake_get_review_state(_sid):  # type: ignore[no-untyped-def]
        return {
            "session_id": _SESSION_ID,
            "review_state": "in_review",
            "review_assigned_to": None,
            "approved_by": None, "approved_at": None,
            "submitted_at": None, "submitted_by": None,
            "history": [],
        }
    monkeypatch.setattr(review_api, "get_review_state", fake_get_review_state)

    resp = client.get(f"/api/sessions/{_SESSION_ID}/review")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "comments" in body
    assert body["comments"]["unresolved"] == 1  # only open_root counts
    assert body["comments"]["total"] == 2       # two roots; reply excluded
