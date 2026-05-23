"""Phase 4 / Week 17 / Day 3 — derived task aggregation + explicit
tasks + my-work view tests.

Nine tests per spec. Tests exercise the service layer (not the
HTTP layer); the HTTP gate ("user can only see own work unless
lead/admin") is verified by patching can_read + the lead/admin
helper directly on the API router.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import collaboration as collab_api
from auth.dependencies import get_current_user
from core.collaboration import (
    explicit_tasks as et_mod,
    my_work as mw_mod,
    tasks as tasks_mod,
)


_FIRM_ID = "11111111-1111-1111-1111-111111111111"
_SESSION_A = "33333333-3333-3333-3333-333333333333"
_SESSION_B = "44444444-4444-4444-4444-444444444444"
_LEAD_ID = "55555555-5555-5555-5555-555555555555"
_CONTRIB_ID = "66666666-6666-6666-6666-666666666666"
_PARTNER_ID = "77777777-7777-7777-7777-777777777777"
_ADMIN_ID = "88888888-8888-8888-8888-888888888888"


def _build_store() -> dict[str, Any]:
    """Two engagements, both with _CONTRIB_ID as a contributor.
    _LEAD_ID leads both. _PARTNER_ID is the reviewer."""
    base = {
        "firm_id": _FIRM_ID,
        "created_by_user_id": _LEAD_ID,
        "review_state": "draft",
        "review_assigned_to": _PARTNER_ID,
    }
    return {
        "sessions": {
            _SESSION_A: {**base, "title": "Engagement A"},
            _SESSION_B: {**base, "title": "Engagement B"},
        },
        "firm_memberships": {
            (_FIRM_ID, _LEAD_ID): "member",
            (_FIRM_ID, _CONTRIB_ID): "member",
            (_FIRM_ID, _PARTNER_ID): "member",
            (_FIRM_ID, _ADMIN_ID): "admin",
        },
        "members": {
            (_SESSION_A, _LEAD_ID): {"role": "lead", "removed_at": None},
            (_SESSION_A, _CONTRIB_ID): {"role": "contributor", "removed_at": None},
            (_SESSION_A, _PARTNER_ID): {"role": "reviewer", "removed_at": None},
            (_SESSION_B, _LEAD_ID): {"role": "lead", "removed_at": None},
            (_SESSION_B, _CONTRIB_ID): {"role": "contributor", "removed_at": None},
        },
        "section_assignments": {},   # (session_id, section_path) -> row
        "review_records": [],        # list of rows
        "comments": {},              # id -> row
        "engagement_tasks": {},      # id -> row
        "audit": [],
    }


def _patch_db(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if "FROM sessions WHERE id" in s and "firm_id" in s and "review_state" not in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"firm_id": sess["firm_id"]} if sess else None
        if "FROM firm_memberships" in s and "role" in s and "SELECT 1" not in s:
            firm, uid = str(args[0]), str(args[1])
            role = store["firm_memberships"].get((firm, uid))
            return {"role": role} if role else None
        if "FROM engagement_memberships em" in s and "JOIN sessions" in s and "em.user_id" in s and "LIMIT 1" not in s and "ORDER BY" not in s:
            sid, uid = str(args[0]), str(args[1])
            m = store["members"].get((sid, uid))
            if m and m["removed_at"] is None:
                return {
                    "id": str(uuid.uuid4()), "engagement_id": sid, "user_id": uid,
                    "role": m["role"], "added_by": _LEAD_ID,
                    "added_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    "removed_at": None, "firm_id": _FIRM_ID,
                }
            return None
        if "engagement_memberships" in s and "role = 'lead'" in s and "LIMIT 1" in s and "<>" not in s and "JOIN" not in s:
            sid = str(args[0])
            for (s_id, u_id), m in store["members"].items():
                if s_id == sid and m["role"] == "lead" and m["removed_at"] is None:
                    return {"user_id": u_id}
            return None
        # explicit_tasks single row
        if "FROM engagement_tasks" in s and "WHERE id" in s:
            tid = str(args[0])
            return store["engagement_tasks"].get(tid)
        # explicit_tasks INSERT
        if "INSERT INTO engagement_tasks" in s and "RETURNING" in s:
            tid = str(uuid.uuid4())
            row = {
                "id": tid, "session_id": str(args[0]), "firm_id": str(args[1]),
                "title": args[2],
                "assigned_to": str(args[3]) if args[3] else None,
                "created_by": str(args[4]),
                "section_path": args[5],
                "done": False, "done_at": None,
                "created_at": datetime.now(tz=timezone.utc),
            }
            store["engagement_tasks"][tid] = row
            return row
        # explicit_tasks UPDATE done
        if "UPDATE engagement_tasks" in s and "SET done = TRUE" in s and "RETURNING" in s:
            tid = str(args[0])
            row = store["engagement_tasks"].get(tid)
            if not row:
                return None
            row["done"] = True
            row["done_at"] = datetime.now(tz=timezone.utc)
            return row
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        # section_incomplete
        if "FROM section_assignments sa" in s and "status <> 'done'" in s:
            uid = str(args[0])
            scope = str(args[1]) if len(args) > 1 else None
            rows = []
            for (sid, path), row in store["section_assignments"].items():
                if row["assigned_to"] != uid or row["status"] == "done":
                    continue
                if scope and sid != scope:
                    continue
                rows.append({
                    "id": row["id"], "session_id": sid, "section_path": path,
                    "status": row["status"], "updated_at": row["updated_at"],
                    "assigned_at": row["assigned_at"],
                    "title": store["sessions"][sid]["title"],
                })
            return rows
        # change_request derivation
        if "FROM review_records rr" in s and "request_changes" in s:
            uid = str(args[0])
            scope = str(args[1]) if len(args) > 1 else None
            rows: list[dict[str, Any]] = []
            for rr in store["review_records"]:
                if rr["action"] != "request_changes":
                    continue
                if scope and rr["session_id"] != scope:
                    continue
                # JOIN section_assignments where assigned_to=uid
                for (sid, path), sa in store["section_assignments"].items():
                    if sid != rr["session_id"] or sa["assigned_to"] != uid:
                        continue
                    rows.append({
                        "review_record_id": rr["id"],
                        "session_id": sid,
                        "feedback": json.dumps(rr["feedback"]),
                        "created_at": rr["created_at"],
                        "title": store["sessions"][sid]["title"],
                        "section_assignment_id": sa["id"],
                        "owned_section_path": path,
                    })
            return rows
        # mentions
        if "FROM comments c" in s and "mentioned_user_ids @>" in s:
            target = json.loads(args[0])[0]
            scope = str(args[1]) if len(args) > 1 else None
            rows = []
            for c in store["comments"].values():
                if c["deleted_at"] is not None:
                    continue
                if scope and c["session_id"] != scope:
                    continue
                if target not in (c.get("mentioned_user_ids") or []):
                    continue
                rows.append({
                    **c,
                    "title": store["sessions"][c["session_id"]]["title"],
                })
            return rows
        # mention root fetch by id
        if "FROM comments c" in s and "JOIN sessions" in s and "id = ANY" in s:
            ids = [str(x) for x in args[0]]
            rows = []
            for c in store["comments"].values():
                if c["id"] in ids:
                    rows.append({
                        **c,
                        "title": store["sessions"][c["session_id"]]["title"],
                    })
            return rows
        # comment on owned section
        if "FROM comments c" in s and "section_assignments sa" in s:
            uid = str(args[0])
            scope = str(args[1]) if len(args) > 1 else None
            rows = []
            for c in store["comments"].values():
                if c["deleted_at"] is not None or c["parent_comment_id"] is not None:
                    continue
                if c["resolved"] or c["anchor_type"] not in ("section", "text_range"):
                    continue
                if c["author_id"] == uid:
                    continue
                if scope and c["session_id"] != scope:
                    continue
                anchor_ref = c["anchor_ref"]
                if isinstance(anchor_ref, str):
                    try:
                        anchor_ref = json.loads(anchor_ref)
                    except Exception:
                        anchor_ref = {}
                path = (anchor_ref or {}).get("section_path")
                if not path:
                    continue
                sa = store["section_assignments"].get((c["session_id"], path))
                if not sa or sa["assigned_to"] != uid:
                    continue
                rows.append({
                    **c,
                    "title": store["sessions"][c["session_id"]]["title"],
                })
            return rows
        # explicit tasks for user (cross-engagement or scoped)
        if "FROM engagement_tasks t" in s and "JOIN sessions" in s:
            uid = str(args[0])
            scope = str(args[1]) if len(args) > 1 else None
            rows = []
            for t in store["engagement_tasks"].values():
                if t.get("assigned_to") != uid or t["done"]:
                    continue
                if scope and t["session_id"] != scope:
                    continue
                rows.append(t)
            return rows
        # explicit tasks for session
        if "FROM engagement_tasks" in s and "WHERE session_id" in s:
            sid = str(args[0])
            return [t for t in store["engagement_tasks"].values()
                    if t["session_id"] == sid]
        # session titles for my_work denormalisation
        if "FROM sessions WHERE id = ANY" in s:
            ids = [str(x) for x in args[0]]
            return [{"id": sid, "title": store["sessions"][sid]["title"]}
                    for sid in ids if sid in store["sessions"]]
        return []

    async def execute(sql: str, *args: Any) -> None:
        s = " ".join(sql.split())
        if "INSERT INTO audit_events" in s:
            store["audit"].append({
                "actor_user_id": args[0],
                "action": args[2],
                "resource_type": args[3],
                "payload": json.loads(args[10]) if len(args) > 10 and args[10] else {},
            })

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

    import audit.queries as _audit_queries
    from core.collaboration import membership as _memb
    monkeypatch.setattr(tasks_mod, "acquire", _acquire)
    monkeypatch.setattr(et_mod, "acquire", _acquire)
    monkeypatch.setattr(mw_mod, "acquire", _acquire)
    monkeypatch.setattr(_memb, "acquire", _acquire)
    monkeypatch.setattr(_audit_queries, "acquire", _acquire)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _seed_section_assignment(store: dict[str, Any], session_id: str,
                              section_path: str, assigned_to: str,
                              status: str = "in_progress") -> str:
    sa_id = str(uuid.uuid4())
    store["section_assignments"][(session_id, section_path)] = {
        "id": sa_id, "session_id": session_id, "firm_id": _FIRM_ID,
        "section_path": section_path,
        "assigned_to": assigned_to, "assigned_by": _LEAD_ID,
        "status": status,
        "assigned_at": _now(), "updated_at": _now(),
    }
    return sa_id


def _seed_review_change_request(store: dict[str, Any], session_id: str,
                                 section_path: str, severity: str = "major",
                                 resolved: bool = False) -> str:
    rr_id = str(uuid.uuid4())
    store["review_records"].append({
        "id": rr_id, "session_id": session_id, "action": "request_changes",
        "feedback": {"overall_note": "X", "severity": severity,
                     "section_pointers": [
                         {"section_path": section_path, "note": "fix it",
                          "severity": severity, "resolved": resolved},
                     ]},
        "created_at": _now(),
    })
    return rr_id


def _seed_comment(store: dict[str, Any], *, session_id: str, author_id: str,
                   anchor_type: str = "section",
                   section_path: str | None = None,
                   mentioned: list[str] | None = None,
                   resolved: bool = False,
                   parent_id: str | None = None) -> str:
    cid = str(uuid.uuid4())
    anchor_ref = {"section_path": section_path} if section_path else {}
    store["comments"][cid] = {
        "id": cid, "session_id": session_id, "firm_id": _FIRM_ID,
        "parent_comment_id": parent_id,
        "anchor_type": anchor_type, "anchor_ref": anchor_ref,
        "body": "body text",
        "mentioned_user_ids": mentioned or [],
        "author_id": author_id,
        "resolved": resolved, "resolved_by": None, "resolved_at": None,
        "created_at": _now(), "updated_at": _now(),
        "edited_at": None, "deleted_at": None,
    }
    return cid


# ---------------------------------------------------------------------------
# 1. Change request on owned section → high-priority derived task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derived_task_from_change_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _seed_section_assignment(store, _SESSION_A, "synergy_estimate", _CONTRIB_ID)
    _seed_review_change_request(store, _SESSION_A, "synergy_estimate",
                                 severity="blocking")

    tasks = await tasks_mod.derive_tasks_for_user(uuid.UUID(_CONTRIB_ID))
    types = [t.task_type for t in tasks]
    assert "change_request" in types
    cr = next(t for t in tasks if t.task_type == "change_request")
    assert cr.priority == "high"
    assert cr.section_path == "synergy_estimate"


# ---------------------------------------------------------------------------
# 2. Mention on a non-owned section → medium derived task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derived_task_from_mention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _seed_comment(
        store, session_id=_SESSION_A, author_id=_LEAD_ID,
        anchor_type="engagement",
        mentioned=[_CONTRIB_ID],
    )

    tasks = await tasks_mod.derive_tasks_for_user(uuid.UUID(_CONTRIB_ID))
    mention_tasks = [t for t in tasks if t.task_type == "mention"]
    assert len(mention_tasks) == 1
    assert mention_tasks[0].priority == "medium"


# ---------------------------------------------------------------------------
# 3. Incomplete owned section → medium derived task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derived_task_from_incomplete_owned_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _seed_section_assignment(store, _SESSION_A, "risks", _CONTRIB_ID,
                              status="in_progress")

    tasks = await tasks_mod.derive_tasks_for_user(uuid.UUID(_CONTRIB_ID))
    section_tasks = [t for t in tasks if t.task_type == "section_incomplete"]
    assert len(section_tasks) == 1
    assert section_tasks[0].section_path == "risks"
    assert section_tasks[0].priority == "medium"


# ---------------------------------------------------------------------------
# 4. Dedup — a comment on owned section that ALSO mentions you is one task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derived_tasks_deduplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unresolved section comment that mentions the contributor
    should produce ONE task (the mention takes precedence over
    comment_on_owned_section), not two."""
    store = _build_store()
    _patch_db(monkeypatch, store)
    _seed_section_assignment(store, _SESSION_A, "synergy_estimate", _CONTRIB_ID)
    _seed_comment(
        store, session_id=_SESSION_A, author_id=_LEAD_ID,
        anchor_type="section", section_path="synergy_estimate",
        mentioned=[_CONTRIB_ID],
    )

    tasks = await tasks_mod.derive_tasks_for_user(uuid.UUID(_CONTRIB_ID))
    by_ref: dict[str, list[str]] = {}
    for t in tasks:
        by_ref.setdefault(t.source_ref, []).append(t.task_type)
    # No source_ref appears more than once with both task types.
    for ref, types in by_ref.items():
        assert len(types) == 1, f"source_ref {ref} duplicated: {types}"
    # And the comment that triggered the mention exists in the
    # output as a "mention", not as a "comment_on_owned_section".
    assert any(t.task_type == "mention" for t in tasks)


# ---------------------------------------------------------------------------
# 5. Explicit task create + complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_task_create_and_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    created = await et_mod.create_task(
        session_id=uuid.UUID(_SESSION_A),
        title="Ping client lawyer about the SPA timeline",
        created_by=uuid.UUID(_LEAD_ID),
        assigned_to=uuid.UUID(_CONTRIB_ID),
        section_path=None,
    )
    assert created.ok, created.reason
    assert created.task.assigned_to == _CONTRIB_ID
    assert created.task.done is False

    completed = await et_mod.complete_task(
        task_id=uuid.UUID(created.task.id),
        actor_id=uuid.UUID(_CONTRIB_ID),
    )
    assert completed.ok
    assert completed.task.done is True
    assert completed.task.done_at is not None


# ---------------------------------------------------------------------------
# 6. my-work aggregates across engagements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_my_work_cross_engagement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Engagement A: contributor owns synergy_estimate (in_progress).
    _seed_section_assignment(store, _SESSION_A, "synergy_estimate", _CONTRIB_ID)
    # Engagement B: contributor was @-mentioned in an engagement-level comment.
    _seed_comment(
        store, session_id=_SESSION_B, author_id=_LEAD_ID,
        anchor_type="engagement", mentioned=[_CONTRIB_ID],
    )

    work = await mw_mod.get_my_work(uuid.UUID(_CONTRIB_ID), scope="all")
    session_ids = {t.session_id for t in work.tasks}
    assert _SESSION_A in session_ids
    assert _SESSION_B in session_ids
    # by_engagement bucket count matches.
    assert set(work.by_engagement.keys()) == {_SESSION_A, _SESSION_B}


# ---------------------------------------------------------------------------
# 7. my-work scoped to a session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_my_work_scoped_to_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    _seed_section_assignment(store, _SESSION_A, "synergy_estimate", _CONTRIB_ID)
    _seed_section_assignment(store, _SESSION_B, "risks", _CONTRIB_ID)

    work = await mw_mod.get_my_work(
        uuid.UUID(_CONTRIB_ID), scope=uuid.UUID(_SESSION_A),
    )
    session_ids = {t.session_id for t in work.tasks}
    assert session_ids == {_SESSION_A}


# ---------------------------------------------------------------------------
# 8. User cannot read another user's work unless lead/admin
# ---------------------------------------------------------------------------


def _build_app(actor_user_id: str, *, can_read: bool = True) -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.include_router(collab_api.router, prefix="/api")

    async def fake_user() -> dict:
        return {"user_id": actor_user_id,
                "email": f"{actor_user_id}@meridian.invalid",
                "role": "member"}

    async def fake_can_read(_engagement_id: str, _user: dict) -> bool:
        return can_read

    app.dependency_overrides[get_current_user] = fake_user
    collab_api.can_read = fake_can_read  # type: ignore[assignment]
    return app, TestClient(app)


@pytest.mark.asyncio
async def test_user_can_only_see_own_work_unless_lead_or_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)
    _seed_section_assignment(store, _SESSION_A, "synergy_estimate", _CONTRIB_ID)

    # Contributor → contributor (self): 200.
    _, client_self = _build_app(_CONTRIB_ID)
    r_self = client_self.get(
        f"/api/sessions/{_SESSION_A}/work?user_id={_CONTRIB_ID}",
    )
    assert r_self.status_code == 200

    # Contributor → lead's work (cross-user, no lead/admin role): 403.
    _, client_intruder = _build_app(_CONTRIB_ID)
    r_intruder = client_intruder.get(
        f"/api/sessions/{_SESSION_A}/work?user_id={_LEAD_ID}",
    )
    assert r_intruder.status_code == 403

    # Lead → contributor's work: 200.
    _, client_lead = _build_app(_LEAD_ID)
    r_lead = client_lead.get(
        f"/api/sessions/{_SESSION_A}/work?user_id={_CONTRIB_ID}",
    )
    assert r_lead.status_code == 200


# ---------------------------------------------------------------------------
# 9. Priority ordering: high before medium before low
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_priority_ordering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Owned section + a blocking change request → high.
    _seed_section_assignment(store, _SESSION_A, "synergy_estimate", _CONTRIB_ID)
    _seed_review_change_request(store, _SESSION_A, "synergy_estimate",
                                 severity="blocking")
    # Plus a mention on a different section → medium.
    _seed_comment(
        store, session_id=_SESSION_A, author_id=_LEAD_ID,
        anchor_type="section", section_path="risks",
        mentioned=[_CONTRIB_ID],
    )
    # Owned section comment authored by another → low.
    _seed_section_assignment(store, _SESSION_A, "next_steps", _CONTRIB_ID)
    _seed_comment(
        store, session_id=_SESSION_A, author_id=_LEAD_ID,
        anchor_type="section", section_path="next_steps",
        mentioned=[],  # no mention this time
    )

    tasks = await tasks_mod.derive_tasks_for_user(uuid.UUID(_CONTRIB_ID))
    priorities = [t.priority for t in tasks]
    # Strictly weakly decreasing (high → medium → low).
    rank = {"high": 0, "medium": 1, "low": 2}
    ranks = [rank[p] for p in priorities]
    assert ranks == sorted(ranks), f"out of order: {priorities}"
    # And the head of the list is the high-priority one.
    assert tasks[0].priority == "high"
    assert tasks[0].task_type == "change_request"
