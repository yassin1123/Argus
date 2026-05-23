"""Phase 4 / Week 16 / Day 4 — engagement comment overview + my-mentions
+ bulk resolve-section tests.

Five tests per spec:

  1. test_artifact_comment_anchored_correctly
  2. test_overview_groups_by_anchor
  3. test_filter_mentioning_user
  4. test_user_can_only_query_own_mentions
  5. test_resolve_all_in_section

Harness mirrors W16/D2 ``test_comments_api.py`` — in-memory DB fake
shared across api.comments, core.comments.threads + service,
audit.queries, plus the new api.users router.
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
from api import users as users_api
from auth.dependencies import get_current_user


_FIRM_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_FIRM_ID = "22222222-2222-2222-2222-222222222222"
_SESSION_ID = "33333333-3333-3333-3333-333333333333"
_AUTHOR_ID = "44444444-4444-4444-4444-444444444444"
_PARTNER_ID = "55555555-5555-5555-5555-555555555555"
_ADMIN_ID = "66666666-6666-6666-6666-666666666666"
_ARTIFACT_ID = "aaaaaaaa-1111-2222-3333-444444444444"


def _build_store() -> dict[str, Any]:
    return {
        "comments": {},
        "audit_events": [],
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
                "artifacts": [
                    {"id": _ARTIFACT_ID,
                     "artifact_type": "deck", "format": "pptx", "status": "ready"},
                ],
            },
        },
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
        "memberships": {
            (_FIRM_ID, _AUTHOR_ID): "member",
            (_FIRM_ID, _PARTNER_ID): "member",
            (_FIRM_ID, _ADMIN_ID): "admin",
        },
    }


def _patch_db(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    """In-memory fake installed across every module that imports
    ``acquire``. The shape mirrors W16/D2 with extra routes for the
    W16/D4 SQL (overview grouping uses the existing list query;
    bulk resolve has a new UPDATE shape; mentions has @> JSONB)."""

    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if "FROM sessions WHERE id" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            if sess is None:
                return None
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
            return store["comments"].get(cid)
        if "FROM firm_memberships" in s and "ORDER BY created_at" in s and "LIMIT 1" in s:
            # api.users._load_user_firm
            uid = str(args[0])
            for firm_id, members in store["firm_members"].items():
                if any(m["user_id"] == uid for m in members):
                    return {"firm_id": firm_id}
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
        if "UPDATE comments" in s and "anchor_ref ->> 'section_path'" in s:
            # bulk_resolve_section
            sid = str(args[0])
            actor = str(args[1])
            sp = str(args[2])
            flipped: list[dict[str, Any]] = []
            for row in store["comments"].values():
                if (row["session_id"] == sid
                        and row["parent_comment_id"] is None
                        and row["deleted_at"] is None
                        and not row["resolved"]
                        and row["anchor_type"] == "section"
                        and isinstance(row["anchor_ref"], dict)
                        and row["anchor_ref"].get("section_path") == sp):
                    row["resolved"] = True
                    row["resolved_by"] = actor
                    row["resolved_at"] = datetime.now(tz=timezone.utc)
                    row["updated_at"] = datetime.now(tz=timezone.utc)
                    flipped.append({"id": row["id"]})
            return flipped
        if "mentioned_user_ids @>" in s:
            # list_mentions_for_user
            target_ids = json.loads(args[0])
            firm_filter = None
            unresolved_only = "resolved = FALSE" in s
            # firm_id param appears before LIMIT when supplied; the
            # last arg is always the LIMIT integer.
            if len(args) >= 3:
                firm_filter = str(args[1])
            target = target_ids[0]
            results: list[dict[str, Any]] = []
            for row in store["comments"].values():
                if row["deleted_at"] is not None:
                    continue
                if target not in [str(x) for x in (row["mentioned_user_ids"] or [])]:
                    continue
                if firm_filter and row["firm_id"] != firm_filter:
                    continue
                if unresolved_only and row["parent_comment_id"] is None and row["resolved"]:
                    continue
                results.append(row)
            results.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
            return results
        if "FROM comments" in s:
            sid = str(args[0])
            rows = [
                r for r in store["comments"].values()
                if r["session_id"] == sid and r["deleted_at"] is None
            ]
            # The query may have an optional anchor_type filter +
            # author_id filter. Detect by arg count vs known shape.
            extras = list(args[1:])
            for ex in extras:
                if isinstance(ex, str) and len(ex) <= 32 and ex in {
                    "engagement", "section", "claim", "text_range", "artifact",
                }:
                    rows = [r for r in rows if r["anchor_type"] == ex]
                elif isinstance(ex, str) and len(ex) == 36:
                    rows = [r for r in rows if r["author_id"] == ex]
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

    import api.comments as _api_comments
    import api.users as _api_users
    import audit.queries as _audit_queries
    import auth.firm_permissions as _firm_perms
    import core.comments.service as _svc
    import core.comments.threads as _threads
    monkeypatch.setattr(_api_comments, "acquire", _acquire)
    monkeypatch.setattr(_api_users, "acquire", _acquire)
    monkeypatch.setattr(_audit_queries, "acquire", _acquire)
    monkeypatch.setattr(_firm_perms, "acquire", _acquire)
    monkeypatch.setattr(_svc, "acquire", _acquire)
    monkeypatch.setattr(_threads, "acquire", _acquire)


def _build_app(user_id: str, *, can_read: bool = True) -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.include_router(comments_api.router, prefix="/api")
    app.include_router(users_api.router, prefix="/api/users")

    async def fake_user() -> dict:
        return {"user_id": user_id, "email": f"{user_id}@meridian.invalid",
                "role": "member"}

    async def fake_can_read(_engagement_id: str, _user: dict) -> bool:
        return can_read

    app.dependency_overrides[get_current_user] = fake_user
    import api.comments as _api_comments
    _api_comments.can_read = fake_can_read  # type: ignore[assignment]
    return app, TestClient(app)


# ---------------------------------------------------------------------------
# 1. Artifact-anchored comments persist with the right ref
# ---------------------------------------------------------------------------


def test_artifact_comment_anchored_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    resp = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={
            "anchor_type": "artifact",
            "anchor_ref": {"artifact_id": _ARTIFACT_ID},
            "body": "Deck needs the synergy slide reworked.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["anchor_type"] == "artifact"
    assert body["anchor_ref"]["artifact_id"] == _ARTIFACT_ID


# ---------------------------------------------------------------------------
# 2. Overview groups threads by anchor
# ---------------------------------------------------------------------------


def test_overview_groups_by_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "section",
              "anchor_ref": {"section_path": "synergy_estimate"},
              "body": "On synergy"},
    )
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "section",
              "anchor_ref": {"section_path": "risks"},
              "body": "On risks"},
    )
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "claim",
              "anchor_ref": {"claim_id": "claim_kgr_1"},
              "body": "On claim"},
    )
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "artifact",
              "anchor_ref": {"artifact_id": _ARTIFACT_ID},
              "body": "On deck"},
    )

    overview = client.get(
        f"/api/sessions/{_SESSION_ID}/comments/overview",
    ).json()
    keys = [g["key"] for g in overview["groups"]]
    # Sections first, then claim, then artifact (W16/D4 grouping order).
    assert keys == [
        "section:risks",
        "section:synergy_estimate",
        "claim:claim_kgr_1",
        f"artifact:{_ARTIFACT_ID}",
    ]
    assert overview["unresolved_total"] == 4
    assert overview["total"] == 4


# ---------------------------------------------------------------------------
# 3. mentioning filter narrows to threads where the user is @-tagged
# ---------------------------------------------------------------------------


def test_filter_mentioning_user(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    # One thread mentions the partner; the other doesn't.
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {},
              "body": "Heads up @sarah.kim — please review."},
    )
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {},
              "body": "No mention here, just a note."},
    )

    filtered = client.get(
        f"/api/sessions/{_SESSION_ID}/comments?mentioning={_PARTNER_ID}",
    ).json()
    assert filtered["total"] == 1
    assert _PARTNER_ID in filtered["threads"][0]["root"]["mentioned_user_ids"]


# ---------------------------------------------------------------------------
# 4. /api/users/{id}/mentions is self-only unless caller is firm admin
# ---------------------------------------------------------------------------


def test_user_can_only_query_own_mentions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Seed a thread mentioning the partner.
    _, author_client = _build_app(_AUTHOR_ID)
    author_client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "engagement", "anchor_ref": {},
              "body": "@sarah.kim look at the synergy basis."},
    )

    # 1. Partner reads their own mentions → 200 with the row.
    _, partner_client = _build_app(_PARTNER_ID)
    resp = partner_client.get(f"/api/users/{_PARTNER_ID}/mentions")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1

    # 2. Author tries to read the partner's mentions → 403.
    _, intruder_client = _build_app(_AUTHOR_ID)
    deny = intruder_client.get(f"/api/users/{_PARTNER_ID}/mentions")
    assert deny.status_code == 403

    # 3. Firm admin reads any member's mentions → 200.
    _, admin_client = _build_app(_ADMIN_ID)
    ok = admin_client.get(f"/api/users/{_PARTNER_ID}/mentions")
    assert ok.status_code == 200
    assert ok.json()["total"] == 1


# ---------------------------------------------------------------------------
# 5. Resolve-all-in-section flips every open thread AND audits each
# ---------------------------------------------------------------------------


def test_resolve_all_in_section(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _, client = _build_app(_AUTHOR_ID)

    # Three threads on synergy_estimate, one already resolved.
    a = client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "section",
              "anchor_ref": {"section_path": "synergy_estimate"},
              "body": "Thread A"},
    ).json()
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "section",
              "anchor_ref": {"section_path": "synergy_estimate"},
              "body": "Thread B"},
    )
    client.post(
        f"/api/sessions/{_SESSION_ID}/comments",
        json={"anchor_type": "section",
              "anchor_ref": {"section_path": "risks"},
              "body": "Different section, untouched"},
    )
    client.post(f"/api/comments/{a['id']}/resolve")

    # Bulk resolve synergy_estimate.
    audit_before = len([e for e in store["audit_events"]
                         if e["action"] == "comment.resolved"])
    resp = client.post(
        f"/api/sessions/{_SESSION_ID}/comments/resolve-section",
        json={"section_path": "synergy_estimate"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Only the second synergy thread was unresolved; A was already
    # closed (so untouched), and the risks thread is on a different
    # section_path (untouched).
    assert body["resolved_count"] == 1
    assert len(body["resolved_comment_ids"]) == 1

    # Per-thread audit event was emitted (W16/D4 hard rule).
    audit_after = len([e for e in store["audit_events"]
                        if e["action"] == "comment.resolved"])
    assert audit_after - audit_before == 1
    bulk_events = [
        e for e in store["audit_events"]
        if e["action"] == "comment.resolved" and e["payload"].get("bulk")
    ]
    assert len(bulk_events) == 1
    assert bulk_events[0]["payload"]["section_path"] == "synergy_estimate"
