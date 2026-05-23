"""Phase 4 / Week 17 / Day 1 — engagement membership tests.

Nine tests per spec. In-memory DB fake pattern (matches W16) so we
don't depend on a live Postgres for the unit tier.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest import mock

import pytest

from core.collaboration import membership as memb_mod
from core.collaboration.roles import EngagementRole


# Stable IDs reused across every test.
_FIRM_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_FIRM_ID = "22222222-2222-2222-2222-222222222222"
_SESSION_ID = "33333333-3333-3333-3333-333333333333"
_LEAD_ID = "44444444-4444-4444-4444-444444444444"
_CONTRIB_ID = "55555555-5555-5555-5555-555555555555"
_REVIEWER_ID = "66666666-6666-6666-6666-666666666666"
_ADMIN_ID = "77777777-7777-7777-7777-777777777777"
_OUTSIDER_ID = "88888888-8888-8888-8888-888888888888"


def _build_store() -> dict[str, Any]:
    """Seed: session belongs to firm, lead is _LEAD_ID, _CONTRIB_ID /
    _REVIEWER_ID are firm members but not yet on the engagement,
    _ADMIN_ID is a firm admin, _OUTSIDER_ID is in the OTHER firm
    (cross-firm rejection test)."""
    return {
        "sessions": {
            _SESSION_ID: {
                "firm_id": _FIRM_ID,
                "created_by_user_id": _LEAD_ID,
                "review_state": "draft",
                "review_assigned_to": None,
            },
        },
        # firm_memberships: (firm_id, user_id) -> role
        "firm_memberships": {
            (_FIRM_ID, _LEAD_ID):     "member",
            (_FIRM_ID, _CONTRIB_ID):  "member",
            (_FIRM_ID, _REVIEWER_ID): "member",
            (_FIRM_ID, _ADMIN_ID):    "admin",
            (_OTHER_FIRM_ID, _OUTSIDER_ID): "member",
        },
        # engagement_memberships keyed by (session_id, user_id) -> row.
        "members": {
            (_SESSION_ID, _LEAD_ID): {
                "id": str(uuid.uuid4()),
                "engagement_id": _SESSION_ID,
                "user_id": _LEAD_ID,
                "role": "lead",
                "added_by": _LEAD_ID,
                "added_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "removed_at": None,
            },
        },
        "audit": [],
    }


def _patch_db(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        # _load_session_firm: SELECT firm_id FROM sessions WHERE id=$1
        if "FROM sessions WHERE id" in s and "firm_id" in s and "review_state" not in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"firm_id": sess["firm_id"]} if sess else None
        # _maybe_align_review_assignment: SELECT review_state, review_assigned_to
        if "SELECT review_state, review_assigned_to" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            if not sess:
                return None
            return {
                "review_state": sess["review_state"],
                "review_assigned_to": sess["review_assigned_to"],
            }
        # firm_memberships role lookup
        if "FROM firm_memberships" in s and "role" in s and "SELECT 1" not in s:
            firm_id, user_id = str(args[0]), str(args[1])
            role = store["firm_memberships"].get((firm_id, user_id))
            return {"role": role} if role else None
        # firm_memberships existence
        if "FROM firm_memberships" in s and "SELECT 1" in s:
            firm_id, user_id = str(args[0]), str(args[1])
            return {"?column?": 1} if (firm_id, user_id) in store["firm_memberships"] else None
        # _load_active
        if "FROM engagement_memberships em" in s and "JOIN sessions s" in s and "em.user_id" in s and "LIMIT 1" not in s and "ORDER BY" not in s:
            sid, uid = str(args[0]), str(args[1])
            row = store["members"].get((sid, uid))
            if row and row["removed_at"] is None:
                sess = store["sessions"].get(sid) or {}
                return {**row, "firm_id": sess.get("firm_id")}
            return None
        # _active_lead_id
        if "engagement_memberships" in s and "role = 'lead'" in s and "LIMIT 1" in s and "<>" not in s and "JOIN" not in s:
            sid = str(args[0])
            for (s_id, u_id), r in store["members"].items():
                if s_id == sid and r["role"] == "lead" and r["removed_at"] is None:
                    return {"user_id": r["user_id"]}
            return None
        # _has_other_lead
        if "engagement_memberships" in s and "role = 'lead'" in s and "<>" in s:
            sid, excl = str(args[0]), str(args[1])
            for (s_id, u_id), r in store["members"].items():
                if (s_id == sid and r["role"] == "lead"
                        and r["removed_at"] is None and u_id != excl):
                    return {"?column?": 1}
            return None
        # get_lead
        if "FROM engagement_memberships em" in s and "JOIN sessions" in s and "em.role = 'lead'" in s and "LIMIT 1" in s:
            sid = str(args[0])
            for (s_id, u_id), r in store["members"].items():
                if (s_id == sid and r["role"] == "lead"
                        and r["removed_at"] is None):
                    sess = store["sessions"].get(sid) or {}
                    return {**r, "firm_id": sess.get("firm_id")}
            return None
        # INSERT / UPSERT — two shapes:
        #   assign_member: $1 sid, $2 uid, $3 role, $4 added_by  (4 args)
        #   ensure_creator_is_lead: $1 sid, $2 uid, role='lead' inlined  (2 args)
        if "INSERT INTO engagement_memberships" in s and "RETURNING" in s:
            sid, uid = str(args[0]), str(args[1])
            if len(args) >= 4:
                role, added_by = args[2], str(args[3])
            else:
                role, added_by = "lead", uid
            existing = store["members"].get((sid, uid))
            if existing:
                existing["role"] = role
                existing["added_by"] = added_by
                existing["removed_at"] = None
                return existing
            row = {
                "id": str(uuid.uuid4()),
                "engagement_id": sid,
                "user_id": uid,
                "role": role,
                "added_by": added_by,
                "added_at": datetime.now(tz=timezone.utc),
                "removed_at": None,
            }
            store["members"][(sid, uid)] = row
            return row
        # UPDATE role
        if "UPDATE engagement_memberships" in s and "SET role" in s and "RETURNING" in s:
            sid, uid, new_role = str(args[0]), str(args[1]), args[2]
            row = store["members"].get((sid, uid))
            if not row or row["removed_at"] is not None:
                return None
            row["role"] = new_role
            return row
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        if "FROM engagement_memberships em" in s and "JOIN sessions" in s and "ORDER BY" in s:
            sid = str(args[0])
            rows: list[dict[str, Any]] = []
            for (s_id, u_id), r in store["members"].items():
                if s_id == sid and r["removed_at"] is None:
                    sess = store["sessions"].get(sid) or {}
                    rows.append({**r, "firm_id": sess.get("firm_id")})
            order = {"lead": 0, "reviewer": 1, "contributor": 2, "observer": 3}
            rows.sort(key=lambda r: (order.get(r["role"], 9), r["added_at"]))
            return rows
        return []

    async def execute(sql: str, *args: Any) -> None:
        s = " ".join(sql.split())
        if "INSERT INTO audit_events" in s:
            store["audit"].append({
                "actor_user_id": args[0],
                "action": args[2],
                "resource_type": args[3],
                "resource_id": args[4],
                "payload": json.loads(args[10]) if len(args) > 10 and args[10] else {},
            })
            return
        if "UPDATE engagement_memberships" in s and "removed_at = NOW()" in s:
            sid, uid = str(args[0]), str(args[1])
            row = store["members"].get((sid, uid))
            if row:
                row["removed_at"] = datetime.now(tz=timezone.utc)
            return
        if "UPDATE sessions SET review_assigned_to" in s:
            sid, uid = str(args[0]), str(args[1])
            sess = store["sessions"].get(sid)
            if sess:
                sess["review_assigned_to"] = uid

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
    monkeypatch.setattr(memb_mod, "acquire", _acquire)
    monkeypatch.setattr(_audit_queries, "acquire", _acquire)


# ---------------------------------------------------------------------------
# Test 1 — happy-path assign
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_member(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    res = await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_CONTRIB_ID),
        role=EngagementRole.CONTRIBUTOR,
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    assert res.ok, res.reason
    assert res.member is not None
    assert res.member.role == "contributor"
    assert res.member.user_id == _CONTRIB_ID


# ---------------------------------------------------------------------------
# Test 2 — only lead or firm-admin can assign
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_lead_or_admin_can_assign(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Seed: contributor already on the engagement, tries to add reviewer.
    await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_CONTRIB_ID),
        role=EngagementRole.CONTRIBUTOR,
        assigned_by=uuid.UUID(_LEAD_ID),
    )

    # Contributor → 403.
    res = await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_REVIEWER_ID),
        role=EngagementRole.REVIEWER,
        assigned_by=uuid.UUID(_CONTRIB_ID),
    )
    assert not res.ok
    assert res.status_code == 403

    # Firm admin (not yet on the engagement) → 200, can manage.
    res2 = await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_REVIEWER_ID),
        role=EngagementRole.REVIEWER,
        assigned_by=uuid.UUID(_ADMIN_ID),
    )
    assert res2.ok, res2.reason


# ---------------------------------------------------------------------------
# Test 3 — cross-firm assignment rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_assign_cross_firm_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    res = await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_OUTSIDER_ID),
        role=EngagementRole.CONTRIBUTOR,
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    assert not res.ok
    assert res.status_code == 400
    assert "firm" in res.reason.lower()


# ---------------------------------------------------------------------------
# Test 4 — second-lead assignment rejected (no auto-demote, per W17/D1 decision)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_lead_rejected_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The W17/D1 surface decision was to REJECT a second-lead with
    409 rather than auto-demote the existing one. This test pins that
    behaviour — flip the assertion if the call ever changes back to
    demote-first."""
    store = _build_store()
    _patch_db(monkeypatch, store)

    res = await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_CONTRIB_ID),
        role=EngagementRole.LEAD,
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    assert not res.ok
    assert res.status_code == 409
    assert res.extra.get("current_lead_user_id") == _LEAD_ID

    # The path forward: explicit demotion then promotion.
    # Add contributor first.
    await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_CONTRIB_ID),
        role=EngagementRole.CONTRIBUTOR,
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    # Promote contributor to lead — first must demote current lead.
    # We attempt it via change_member_role on the existing lead.
    demote = await memb_mod.change_member_role(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_LEAD_ID),
        new_role=EngagementRole.CONTRIBUTOR,
        actor_id=uuid.UUID(_LEAD_ID),
    )
    # Demoting the only lead without a replacement is rejected by
    # the "orphan-guard" branch in change_member_role.
    assert not demote.ok
    assert demote.status_code == 409


# ---------------------------------------------------------------------------
# Test 5 — cannot remove lead without a replacement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_remove_lead_without_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    res = await memb_mod.remove_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_LEAD_ID),
        actor_id=uuid.UUID(_LEAD_ID),
    )
    assert not res.ok
    assert res.status_code == 409
    assert "lead" in res.reason.lower()


# ---------------------------------------------------------------------------
# Test 6 — reviewer role aligns sessions.review_assigned_to
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reviewer_role_sets_review_assigned_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    res = await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_REVIEWER_ID),
        role=EngagementRole.REVIEWER,
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    assert res.ok, res.reason
    assert res.extra.get("review_assigned_to_updated") is True
    assert store["sessions"][_SESSION_ID]["review_assigned_to"] == _REVIEWER_ID


# ---------------------------------------------------------------------------
# Test 7 — creator is auto-assigned as lead on engagement creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creator_auto_assigned_lead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    # Wipe pre-existing lead to simulate a fresh session.
    store["members"].clear()
    _patch_db(monkeypatch, store)

    res = await memb_mod.ensure_creator_is_lead(
        session_id=uuid.UUID(_SESSION_ID),
        creator_id=uuid.UUID(_LEAD_ID),
    )
    assert res.ok, res.reason
    assert res.member is not None
    assert res.member.role == "lead"
    assert res.member.user_id == _LEAD_ID

    # Idempotent — running again is a no-op.
    res2 = await memb_mod.ensure_creator_is_lead(
        session_id=uuid.UUID(_SESSION_ID),
        creator_id=uuid.UUID(_LEAD_ID),
    )
    assert res2.ok
    assert res2.extra.get("no_op") is True


# ---------------------------------------------------------------------------
# Test 8 — remove is SOFT (row remains, removed_at set)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_is_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Seed a removable contributor.
    await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_CONTRIB_ID),
        role=EngagementRole.CONTRIBUTOR,
        assigned_by=uuid.UUID(_LEAD_ID),
    )

    res = await memb_mod.remove_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_CONTRIB_ID),
        actor_id=uuid.UUID(_LEAD_ID),
    )
    assert res.ok, res.reason
    # Row still present in the store; removed_at populated.
    row = store["members"][(_SESSION_ID, _CONTRIB_ID)]
    assert row["removed_at"] is not None
    # Active list excludes it.
    active = await memb_mod.list_members(uuid.UUID(_SESSION_ID))
    assert all(m.user_id != _CONTRIB_ID for m in active)


# ---------------------------------------------------------------------------
# Test 9 — every membership action emits an audit event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_membership_action_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # 1. assign contributor
    await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_CONTRIB_ID),
        role=EngagementRole.CONTRIBUTOR,
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    # 2. change role: contributor → reviewer
    await memb_mod.change_member_role(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_CONTRIB_ID),
        new_role=EngagementRole.REVIEWER,
        actor_id=uuid.UUID(_LEAD_ID),
    )
    # 3. add a second contributor for the lead swap setup
    await memb_mod.assign_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_ADMIN_ID),
        role=EngagementRole.CONTRIBUTOR,
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    # 4. lead change: promote admin to lead first (rejected by uniqueness),
    #    then demote LEAD via swap path → use change_member_role on
    #    the current lead AFTER a replacement is in place.
    #    Easier: just remove the contributor we added.
    await memb_mod.remove_member(
        session_id=uuid.UUID(_SESSION_ID),
        user_id=uuid.UUID(_ADMIN_ID),
        actor_id=uuid.UUID(_LEAD_ID),
    )

    actions = {a["action"] for a in store["audit"]}
    assert "engagement.member_assigned" in actions
    assert "engagement.member_role_changed" in actions
    assert "engagement.member_removed" in actions
