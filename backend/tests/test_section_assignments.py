"""Phase 4 / Week 17 / Day 2 — section ownership + work-status tests.

Nine tests per spec. In-memory DB fake mirroring the W17/D1 pattern,
extended with:

  - ``section_assignments`` table backing (keyed by
    (session_id, section_path))
  - ``reports`` row backing (the W17/D2 service validates
    section_path against the live consulting_payload)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest import mock

import pytest

from core.collaboration import (
    section_assignments as sa_mod,
    coverage as cov_mod,
    membership as memb_mod,
)
from core.collaboration.section_status import SectionStatus


_FIRM_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_FIRM_ID = "22222222-2222-2222-2222-222222222222"
_SESSION_ID = "33333333-3333-3333-3333-333333333333"
_LEAD_ID = "44444444-4444-4444-4444-444444444444"
_CONTRIB_ID = "55555555-5555-5555-5555-555555555555"
_OTHER_CONTRIB_ID = "66666666-6666-6666-6666-666666666666"
_ADMIN_ID = "77777777-7777-7777-7777-777777777777"
_OUTSIDER_ID = "88888888-8888-8888-8888-888888888888"


def _build_store() -> dict[str, Any]:
    return {
        "sessions": {
            _SESSION_ID: {
                "firm_id": _FIRM_ID,
                "created_by_user_id": _LEAD_ID,
                "review_state": "draft",
                "review_assigned_to": None,
            },
        },
        "firm_memberships": {
            (_FIRM_ID, _LEAD_ID): "member",
            (_FIRM_ID, _CONTRIB_ID): "member",
            (_FIRM_ID, _OTHER_CONTRIB_ID): "member",
            (_FIRM_ID, _ADMIN_ID): "admin",
            (_OTHER_FIRM_ID, _OUTSIDER_ID): "member",
        },
        # engagement_memberships
        "members": {
            (_SESSION_ID, _LEAD_ID): {
                "id": str(uuid.uuid4()), "engagement_id": _SESSION_ID,
                "user_id": _LEAD_ID, "role": "lead",
                "added_by": _LEAD_ID,
                "added_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "removed_at": None,
            },
            (_SESSION_ID, _CONTRIB_ID): {
                "id": str(uuid.uuid4()), "engagement_id": _SESSION_ID,
                "user_id": _CONTRIB_ID, "role": "contributor",
                "added_by": _LEAD_ID,
                "added_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "removed_at": None,
            },
            (_SESSION_ID, _OTHER_CONTRIB_ID): {
                "id": str(uuid.uuid4()), "engagement_id": _SESSION_ID,
                "user_id": _OTHER_CONTRIB_ID, "role": "contributor",
                "added_by": _LEAD_ID,
                "added_at": datetime(2026, 1, 3, tzinfo=timezone.utc),
                "removed_at": None,
            },
        },
        # section_assignments keyed by (session_id, section_path)
        "section_assignments": {},
        # reports row for the W9 addressing validation. Top-level
        # base keys + consulting_payload subkeys after flattening.
        "report_payload": {
            "summary": "Synergy basis carries the recommendation.",
            "key_reasons": [{"text": "Resilient gross margin",
                             "claim_id": "claim_kgr_1"}],
            "risks": [], "counterarguments": [], "next_steps": [],
            "sources": [], "caveats": "",
            "consulting_payload": {
                "synergy_estimate": {
                    "revenue_synergies": [
                        {"type": "Cross-sell",
                         "magnitude_gbp_m": 5.0,
                         "basis_citations": ["claim_kgr_1"]},
                    ],
                    "cost_synergies": [],
                },
                "target_overview": {"company": "Kestrel"},
                "valuation_range": {"low": 80, "high": 120},
            },
        },
        "audit": [],
    }


def _patch_db(monkeypatch: pytest.MonkeyPatch, store: dict[str, Any]) -> None:
    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        # Session firm
        if "FROM sessions WHERE id" in s and "firm_id" in s and "review_state" not in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            return {"firm_id": sess["firm_id"]} if sess else None
        if "SELECT review_state, review_assigned_to" in s:
            sid = str(args[0])
            sess = store["sessions"].get(sid)
            if not sess:
                return None
            return {"review_state": sess["review_state"],
                    "review_assigned_to": sess["review_assigned_to"]}
        # firm_memberships role
        if "FROM firm_memberships" in s and "role" in s and "SELECT 1" not in s:
            firm_id, user_id = str(args[0]), str(args[1])
            role = store["firm_memberships"].get((firm_id, user_id))
            return {"role": role} if role else None
        if "FROM firm_memberships" in s and "SELECT 1" in s:
            firm_id, user_id = str(args[0]), str(args[1])
            return {"?column?": 1} if (firm_id, user_id) in store["firm_memberships"] else None
        # engagement_memberships active row
        if "FROM engagement_memberships em" in s and "JOIN sessions" in s and "em.user_id" in s and "LIMIT 1" not in s and "ORDER BY" not in s:
            sid, uid = str(args[0]), str(args[1])
            row = store["members"].get((sid, uid))
            if row and row["removed_at"] is None:
                return {**row, "firm_id": store["sessions"][sid]["firm_id"]}
            return None
        # active lead id
        if "engagement_memberships" in s and "role = 'lead'" in s and "LIMIT 1" in s and "<>" not in s and "JOIN" not in s:
            sid = str(args[0])
            for (s_id, u_id), r in store["members"].items():
                if s_id == sid and r["role"] == "lead" and r["removed_at"] is None:
                    return {"user_id": r["user_id"]}
            return None
        # reports
        if "FROM reports WHERE session_id" in s:
            sid = str(args[0])
            if sid != _SESSION_ID:
                return None
            p = store["report_payload"]
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
        # section_assignments single row
        if "FROM section_assignments" in s and "WHERE session_id" in s and "section_path" in s and "ORDER BY" not in s:
            sid, path = str(args[0]), args[1]
            row = store["section_assignments"].get((sid, path))
            return row
        # section_assignments INSERT / UPSERT
        if "INSERT INTO section_assignments" in s and "RETURNING" in s:
            sid, firm, path, assigned_to, assigned_by = (
                str(args[0]), str(args[1]), args[2], str(args[3]), str(args[4]),
            )
            existing = store["section_assignments"].get((sid, path))
            now = datetime.now(tz=timezone.utc)
            if existing:
                existing["assigned_to"] = assigned_to
                existing["assigned_by"] = assigned_by
                existing["updated_at"] = now
                return existing
            row = {
                "id": str(uuid.uuid4()),
                "session_id": sid, "firm_id": firm,
                "section_path": path,
                "assigned_to": assigned_to,
                "assigned_by": assigned_by,
                "status": "not_started",
                "assigned_at": now, "updated_at": now,
            }
            store["section_assignments"][(sid, path)] = row
            return row
        # section_assignments UPDATE status
        if "UPDATE section_assignments" in s and "SET status" in s and "RETURNING" in s:
            sid, path, status = str(args[0]), args[1], args[2]
            row = store["section_assignments"].get((sid, path))
            if not row:
                return None
            row["status"] = status
            row["updated_at"] = datetime.now(tz=timezone.utc)
            return row
        # section_assignments UPDATE unassign
        if "UPDATE section_assignments" in s and "assigned_to = NULL" in s and "RETURNING" in s:
            sid, path = str(args[0]), args[1]
            row = store["section_assignments"].get((sid, path))
            if not row:
                return None
            row["assigned_to"] = None
            row["status"] = "not_started"
            row["updated_at"] = datetime.now(tz=timezone.utc)
            return row
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        if "FROM section_assignments" in s and "ORDER BY section_path" in s:
            sid = str(args[0])
            rows = [r for (s_id, _p), r in store["section_assignments"].items() if s_id == sid]
            rows.sort(key=lambda r: r["section_path"])
            return rows
        if "FROM section_assignments" in s and "assigned_to = $1" in s:
            uid = str(args[0])
            scope_sid = str(args[1]) if len(args) > 1 else None
            rows = []
            for (s_id, _p), r in store["section_assignments"].items():
                if r.get("assigned_to") != uid:
                    continue
                if scope_sid and s_id != scope_sid:
                    continue
                rows.append(r)
            rows.sort(key=lambda r: r["section_path"])
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
    monkeypatch.setattr(sa_mod, "acquire", _acquire)
    monkeypatch.setattr(cov_mod, "list_section_assignments",
                        sa_mod.list_section_assignments)
    monkeypatch.setattr(cov_mod, "_load_payload", sa_mod._load_payload)
    monkeypatch.setattr(memb_mod, "acquire", _acquire)
    monkeypatch.setattr(_audit_queries, "acquire", _acquire)


# ---------------------------------------------------------------------------
# 1. Assign a section to a member
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_section_to_member(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    res = await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        assigned_to=uuid.UUID(_CONTRIB_ID),
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    assert res.ok, res.reason
    assert res.assignment is not None
    assert res.assignment.section_path == "synergy_estimate"
    assert res.assignment.assigned_to == _CONTRIB_ID
    assert res.assignment.status == SectionStatus.NOT_STARTED.value


# ---------------------------------------------------------------------------
# 2. Cannot assign a non-engagement-member
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_section_requires_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # OUTSIDER_ID isn't on the engagement.
    res = await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        assigned_to=uuid.UUID(_OUTSIDER_ID),
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    assert not res.ok
    assert res.status_code == 400
    assert "engagement member" in res.reason.lower()


# ---------------------------------------------------------------------------
# 3. Only lead or firm admin can assign
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_lead_or_admin_assigns_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    res = await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        assigned_to=uuid.UUID(_OTHER_CONTRIB_ID),
        assigned_by=uuid.UUID(_CONTRIB_ID),  # contributor, not lead
    )
    assert not res.ok
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 4. Owner can change own section status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_can_change_own_section_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        assigned_to=uuid.UUID(_CONTRIB_ID),
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    res = await sa_mod.set_section_status(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        status=SectionStatus.IN_PROGRESS,
        actor_id=uuid.UUID(_CONTRIB_ID),
    )
    assert res.ok, res.reason
    assert res.assignment.status == SectionStatus.IN_PROGRESS.value


# ---------------------------------------------------------------------------
# 5. Contributor cannot change someone else's section status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contributor_cannot_change_others_section_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        assigned_to=uuid.UUID(_CONTRIB_ID),
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    res = await sa_mod.set_section_status(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        status=SectionStatus.DONE,
        actor_id=uuid.UUID(_OTHER_CONTRIB_ID),  # not the owner
    )
    assert not res.ok
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 6. section_path validated against live payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_path_validated_against_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    res = await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="does_not_exist_in_payload",
        assigned_to=uuid.UUID(_CONTRIB_ID),
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    assert not res.ok
    assert res.status_code == 400
    assert "section_path" in res.reason.lower()


# ---------------------------------------------------------------------------
# 7. Coverage map surfaces unassigned sections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coverage_map_surfaces_unassigned_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Assign one section; leave the rest unassigned.
    await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        assigned_to=uuid.UUID(_CONTRIB_ID),
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    cov = await cov_mod.section_coverage(uuid.UUID(_SESSION_ID))
    # The seed has summary, key_reasons, risks, counterarguments, next_steps,
    # synergy_estimate, target_overview, valuation_range — 8 trackable
    # sections present in payload. One is assigned; the rest are unassigned.
    assert cov.unassigned_count >= 1
    assigned_paths = {e.section_path for e in cov.entries if e.assigned}
    assert "synergy_estimate" in assigned_paths
    unassigned_paths = {e.section_path for e in cov.entries if not e.assigned}
    assert "summary" in unassigned_paths


# ---------------------------------------------------------------------------
# 8. All done → ready_to_submit advisory flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_done_surfaces_ready_to_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _build_store()
    _patch_db(monkeypatch, store)

    # Walk every trackable section present in the payload, assign it,
    # mark it done.
    cov_initial = await cov_mod.section_coverage(uuid.UUID(_SESSION_ID))
    assert cov_initial.ready_to_submit is False
    paths = [e.section_path for e in cov_initial.entries]

    for p in paths:
        await sa_mod.assign_section(
            session_id=uuid.UUID(_SESSION_ID),
            section_path=p,
            assigned_to=uuid.UUID(_CONTRIB_ID),
            assigned_by=uuid.UUID(_LEAD_ID),
        )
        await sa_mod.set_section_status(
            session_id=uuid.UUID(_SESSION_ID),
            section_path=p,
            status=SectionStatus.DONE,
            actor_id=uuid.UUID(_CONTRIB_ID),
        )

    cov_done = await cov_mod.section_coverage(uuid.UUID(_SESSION_ID))
    assert cov_done.unassigned_count == 0
    assert cov_done.ready_to_submit is True
    # Per W17/D2 hard rule: surface only, no auto-submit.
    assert store["sessions"][_SESSION_ID]["review_state"] == "draft"


# ---------------------------------------------------------------------------
# 9. Section status is distinct from engagement review_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_status_distinct_from_engagement_review_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A section can be ``done`` while the engagement stays in
    ``draft``. The W15 review state machine is independent."""
    store = _build_store()
    _patch_db(monkeypatch, store)

    await sa_mod.assign_section(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        assigned_to=uuid.UUID(_CONTRIB_ID),
        assigned_by=uuid.UUID(_LEAD_ID),
    )
    await sa_mod.set_section_status(
        session_id=uuid.UUID(_SESSION_ID),
        section_path="synergy_estimate",
        status=SectionStatus.DONE,
        actor_id=uuid.UUID(_CONTRIB_ID),
    )

    # Section is done — engagement review_state is unchanged.
    assert store["sessions"][_SESSION_ID]["review_state"] == "draft"
    # And the audit row distinguishes the two: section.status_changed
    # rather than review.*.
    section_actions = [a["action"] for a in store["audit"]
                        if a["action"].startswith("section.")]
    review_actions = [a["action"] for a in store["audit"]
                       if a["action"].startswith("review.")]
    assert "section.status_changed" in section_actions
    assert review_actions == []
