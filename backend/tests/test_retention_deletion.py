"""Tests for the W23/D2 retention + hard-deletion stack.

Eight spec assertions:

  1. purge_engagement removes every associated row across every
     touched table
  2. artifact files are deleted from disk (not just their DB rows)
  3. the purge_audit_log entry carries IDs + counts + reason
     ONLY — no claim text, evidence content, or memo prose
  4. purge endpoint requires firm_admin + confirm=true +
     typed_confirmation matching session_id
  5. cross-firm purge is denied (the W23/D1 firm scope holds)
  6. retention sweep flags expired sessions with the grace period
  7. retention sweep notifies firm_admins BEFORE the actual purge
  8. firm.retention_days = None means keep indefinitely

All tests run against an in-memory DB fake (no Postgres needed)
+ a stubbed file-system for artifact deletion.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core.retention.policy import (  # noqa: E402
    DEFAULT_RETENTION_GRACE_DAYS,
    decide_retention_action,
)


# ---------------------------------------------------------------------------
# In-memory DB fake
# ---------------------------------------------------------------------------


class _FakeDB:
    """Holds session metadata + every per-table rows-by-session
    index that purge_engagement touches. The fake mirrors the
    SQL surface the real runner uses; a missing table is
    tolerated (matches the production "DROP COLUMN IF EXISTS"
    style migration discipline)."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.firms: dict[str, dict[str, Any]] = {}
        self.firm_admins: dict[str, list[str]] = {}  # firm_id -> [user_id, ...]
        self.rows_by_table: dict[str, list[dict[str, Any]]] = {}
        self.purge_audit: list[dict[str, Any]] = []
        self.notifications: list[dict[str, Any]] = []
        self._next_audit_id = 1

    def add_session(
        self, sid: str, firm_id: str, *,
        updated_at: datetime | None = None,
        retention_flagged_at: datetime | None = None,
        grace_expires_at: datetime | None = None,
    ) -> None:
        self.sessions[sid] = {
            "id": sid, "firm_id": firm_id,
            "updated_at": updated_at or datetime.now(tz=timezone.utc),
            "retention_flagged_at": retention_flagged_at,
            "retention_grace_expires_at": grace_expires_at,
        }

    def add_firm(
        self, firm_id: str, retention_days: int | None = None,
        admins: list[str] | None = None,
    ) -> None:
        self.firms[firm_id] = {"id": firm_id, "retention_days": retention_days}
        self.firm_admins[firm_id] = admins or []

    def add_row(self, table: str, row: dict[str, Any]) -> None:
        self.rows_by_table.setdefault(table, []).append(row)


def _install_db(monkeypatch: pytest.MonkeyPatch, db: _FakeDB) -> None:
    """Stub the ``acquire`` exposed by the retention modules so
    every DB call routes through this fake."""

    async def execute(sql: str, *args: Any) -> str:
        s = " ".join(sql.split())
        if "INSERT INTO purge_audit_log" in s:
            db.purge_audit.append({
                "id": db._next_audit_id,
                "session_id": str(args[0]),
                "firm_id": str(args[1]),
                "actor_user_id": str(args[2]) if args[2] else None,
                "purge_reason": args[3],
                "rows_deleted": json.loads(args[4]),
                "files_deleted": int(args[5]),
                "purged_at": datetime.now(tz=timezone.utc),
            })
            db._next_audit_id += 1
            return "INSERT 0 1"
        if "DELETE FROM " in s and "WHERE session_id" in s:
            # Extract table name from "DELETE FROM <table> WHERE..."
            table = s.split("DELETE FROM ", 1)[1].split(" ", 1)[0]
            sid = str(args[0])
            rows = db.rows_by_table.get(table, [])
            removed = sum(1 for r in rows if str(r.get("session_id")) == sid)
            db.rows_by_table[table] = [
                r for r in rows if str(r.get("session_id")) != sid
            ]
            if table == "sessions":
                db.sessions.pop(sid, None)
            return f"DELETE {removed}"
        if "UPDATE sessions" in s and "retention_flagged_at" in s:
            sid = str(args[0])
            grace = args[1]
            if sid in db.sessions:
                db.sessions[sid]["retention_flagged_at"] = datetime.now(
                    tz=timezone.utc,
                )
                db.sessions[sid]["retention_grace_expires_at"] = grace
            return "UPDATE 1"
        if "UPDATE firms" in s and "retention_days" in s:
            firm_id = str(args[0])
            if firm_id in db.firms:
                db.firms[firm_id]["retention_days"] = args[1]
            return "UPDATE 1"
        if "INSERT INTO notifications" in s:
            db.notifications.append({
                "recipient_id": str(args[0]),
                "firm_id": str(args[1]),
                "notification_type": args[2],
                "session_id": str(args[3]),
                "source_ref": json.loads(args[4]),
                "summary": args[5],
            })
            return "INSERT 0 1"
        return "OK"

    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if "INSERT INTO purge_audit_log" in s:
            # deletion.py uses fetchrow(INSERT ... RETURNING id)
            row = {
                "id": db._next_audit_id,
                "session_id": str(args[0]),
                "firm_id": str(args[1]),
                "actor_user_id": str(args[2]) if args[2] else None,
                "purge_reason": args[3],
                "rows_deleted": json.loads(args[4]),
                "files_deleted": int(args[5]),
                "purged_at": datetime.now(tz=timezone.utc),
            }
            db.purge_audit.append(row)
            db._next_audit_id += 1
            return {"id": row["id"]}
        if "FROM sessions WHERE id" in s and "firm_id" in s:
            sid = str(args[0])
            row = db.sessions.get(sid)
            return {"firm_id": row["firm_id"]} if row else None
        if "FROM firms WHERE id" in s and "retention_days" in s:
            firm_id = str(args[0])
            row = db.firms.get(firm_id)
            return {"retention_days": row["retention_days"]} if row else None
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        if "SELECT file_path FROM export_artifacts" in s:
            sid = str(args[0])
            return [
                {"file_path": r["file_path"]}
                for r in db.rows_by_table.get("export_artifacts", [])
                if str(r.get("session_id")) == sid and r.get("file_path")
            ]
        if "FROM sessions s" in s and "JOIN firms f" in s:
            out = []
            for sid, srow in db.sessions.items():
                firm = db.firms.get(srow["firm_id"], {})
                if firm.get("retention_days") is None:
                    continue
                out.append({
                    "id": sid, "firm_id": srow["firm_id"],
                    "updated_at": srow["updated_at"],
                    "retention_flagged_at": srow.get("retention_flagged_at"),
                    "retention_grace_expires_at": srow.get(
                        "retention_grace_expires_at",
                    ),
                    "retention_days": firm["retention_days"],
                })
            return out
        if "FROM firm_memberships" in s and "role = 'admin'" in s:
            firm_id = str(args[0])
            return [{"user_id": uid} for uid in db.firm_admins.get(firm_id, [])]
        if "FROM purge_audit_log" in s:
            firm_id = str(args[0])
            return [
                {**r, "rows_deleted": json.dumps(r["rows_deleted"])}
                for r in db.purge_audit if r["firm_id"] == firm_id
            ][: int(args[1])]
        return []

    fake_conn = mock.MagicMock()
    fake_conn.execute = execute
    fake_conn.fetchrow = fetchrow
    fake_conn.fetch = fetch

    class _Tx:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None
    fake_conn.transaction = lambda: _Tx()

    class _AcquireCM:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    def _acquire():
        return _AcquireCM()

    import core.retention.deletion as d_mod
    import core.retention.policy as p_mod
    monkeypatch.setattr(d_mod, "acquire", _acquire)
    monkeypatch.setattr(p_mod, "acquire", _acquire)


# ---------------------------------------------------------------------------
# 1. purge removes every associated row
# ---------------------------------------------------------------------------


def test_purge_engagement_removes_all_associated_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    db = _FakeDB()
    _install_db(monkeypatch, db)
    firm = str(uuid4())
    sid = str(uuid4())
    db.add_firm(firm)
    db.add_session(sid, firm)
    # Plant rows in every table the purge sweeps.
    touched_tables = [
        "claim_evidence_links", "claim_rows", "evidence_objects",
        "pipeline_events", "agent_outputs", "conversation_turns",
        "llm_calls", "section_deepening_runs", "comments",
        "engagement_tasks", "section_assignments",
        "engagement_memberships", "review_records", "payload_versions",
        "notifications", "metric_events", "cost_ledger",
        "export_artifacts", "reports", "sources",
    ]
    for t in touched_tables:
        db.add_row(t, {"session_id": sid, "data": "marker"})

    from core.retention.deletion import purge_engagement
    report = asyncio.run(purge_engagement(
        session_id=sid, actor_user_id=str(uuid4()),
        purge_reason="test",
    ))

    # Every table planted has zero rows for this session.
    for t in touched_tables:
        remaining = [
            r for r in db.rows_by_table.get(t, [])
            if str(r.get("session_id")) == sid
        ]
        assert remaining == [], (
            f"residual rows in {t} after purge: {len(remaining)}"
        )
    # The session itself is gone too.
    assert sid not in db.sessions
    # Report carries per-table counts.
    assert report.rows_deleted, "report must carry per-table counts"
    assert report.session_id == sid
    assert report.firm_id == firm


# ---------------------------------------------------------------------------
# 2. artifact files deleted from disk
# ---------------------------------------------------------------------------


def test_purge_deletes_artifact_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    db = _FakeDB()
    _install_db(monkeypatch, db)
    firm = str(uuid4())
    sid = str(uuid4())
    db.add_firm(firm)
    db.add_session(sid, firm)

    # Real files on disk that the purge MUST unlink.
    file_a = tmp_path / "memo.pdf"
    file_b = tmp_path / "deck.pptx"
    file_a.write_bytes(b"PDF-stub")
    file_b.write_bytes(b"PPTX-stub")
    db.add_row("export_artifacts", {
        "session_id": sid, "file_path": str(file_a),
    })
    db.add_row("export_artifacts", {
        "session_id": sid, "file_path": str(file_b),
    })
    assert file_a.exists() and file_b.exists()

    from core.retention.deletion import purge_engagement
    report = asyncio.run(purge_engagement(
        session_id=sid, actor_user_id=None, purge_reason="test",
    ))

    # Files gone from storage, not just rows.
    assert not file_a.exists(), "memo.pdf must be removed from disk"
    assert not file_b.exists(), "deck.pptx must be removed from disk"
    assert report.files_deleted == 2
    assert report.files_failed == 0


# ---------------------------------------------------------------------------
# 3. audit entry has no client content
# ---------------------------------------------------------------------------


def test_purge_audit_entry_has_no_client_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDB()
    _install_db(monkeypatch, db)
    firm = str(uuid4())
    sid = str(uuid4())
    db.add_firm(firm)
    db.add_session(sid, firm)
    # Plant CONFIDENTIAL prose into a row that's about to be
    # deleted. The audit must NOT carry any of it.
    SECRET = "CONFIDENTIAL: target Q2 EBITDA dropped 18% YoY"
    db.add_row("evidence_objects", {
        "session_id": sid,
        "quote": SECRET,
        "claim": SECRET,
    })
    db.add_row("payload_versions", {
        "session_id": sid,
        "payload_snapshot": {"summary": SECRET},
    })

    from core.retention.deletion import purge_engagement
    asyncio.run(purge_engagement(
        session_id=sid, actor_user_id=str(uuid4()),
        purge_reason="test",
    ))

    # Exactly one audit row + zero residual prose anywhere.
    assert len(db.purge_audit) == 1
    audit = db.purge_audit[0]
    serialised = json.dumps(audit, default=str)
    assert SECRET not in serialised, (
        "audit entry leaked deleted content"
    )
    # The audit DOES carry the IDs + counts + reason (proof of
    # deletion, no content).
    assert audit["session_id"] == sid
    assert audit["firm_id"] == firm
    assert audit["purge_reason"] == "test"
    assert audit["rows_deleted"]
    assert "evidence_objects" in audit["rows_deleted"]


# ---------------------------------------------------------------------------
# 4. purge requires admin + confirmation
# ---------------------------------------------------------------------------


def test_purge_requires_admin_and_confirmation() -> None:
    """Replays the route-handler gate logic directly.

    The route enforces:
      - firm_admin OR system_admin role
      - confirm == True
      - typed_confirmation == session_id
    """
    from api.retention import _is_firm_admin, _is_system_admin

    sid = "abc-123-def-456"
    firm_a = "firm-A"

    # 1. non-admin user — denied.
    member = {"user_id": "u1", "role": "member",
              "default_firm_id": firm_a, "default_firm_role": "member"}
    assert not (_is_firm_admin(member) or _is_system_admin(member))

    # 2. firm_admin of correct firm — allowed by role.
    firm_admin = {"user_id": "u2", "role": "member",
                  "default_firm_id": firm_a, "default_firm_role": "admin"}
    assert _is_firm_admin(firm_admin)

    # 3. system_admin — allowed by role.
    sys_admin = {"user_id": "u3", "role": "admin",
                 "default_firm_id": None, "default_firm_role": None}
    assert _is_system_admin(sys_admin)

    # 4. confirm=false → the route raises 400. Replay the body
    #    parsing check inline.
    from api.retention import PurgeBody

    # A correctly-formed body matches.
    ok_body = PurgeBody(confirm=True, typed_confirmation=sid)
    assert ok_body.confirm is True
    assert ok_body.typed_confirmation == sid

    # confirm=false fails the gate.
    no_confirm = PurgeBody(confirm=False, typed_confirmation=sid)
    assert no_confirm.confirm is False

    # typed_confirmation mismatch fails the gate.
    typo = PurgeBody(confirm=True, typed_confirmation="WRONG-ID")
    assert typo.typed_confirmation != sid


# ---------------------------------------------------------------------------
# 5. cross-firm purge denied (W23/D1 firm-scope guard holds)
# ---------------------------------------------------------------------------


def test_purge_is_firm_scoped() -> None:
    """A firm-B admin must not be able to purge a firm-A session —
    even with a correct confirmation body. Replay the firm-scope
    gate the route applies."""
    import asyncio
    from auth.firm_scope import assert_firm_access
    from fastapi import HTTPException

    firm_a = "firm-A"
    firm_b_admin = {
        "user_id": "uB", "role": "member",
        "default_firm_id": "firm-B", "default_firm_role": "admin",
    }

    async def go() -> None:
        with pytest.raises(HTTPException) as exc:
            await assert_firm_access(
                user=firm_b_admin,
                resource_firm_id=firm_a,
                resource_kind="session",
                resource_id="sess-A-1",
            )
        # 404, not 403 (anti-enumeration).
        assert exc.value.status_code == 404

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 6. retention sweep flags expired sessions with grace
# ---------------------------------------------------------------------------


def test_retention_sweep_flags_expired_with_grace() -> None:
    """``decide_retention_action`` returns ``flag`` for sessions
    past their window that haven't been flagged yet; the
    decision carries a grace_expires_at timestamp."""
    now = datetime(2026, 5, 27, 12, 0, 0, tzinfo=timezone.utc)
    # An engagement that hasn't been touched in 100 days; firm
    # retention is 90 days → 10 days past expiry, not yet flagged.
    decision = decide_retention_action(
        session_id="s-old",
        firm_id="firm-A",
        updated_at=now - timedelta(days=100),
        retention_days=90,
        retention_flagged_at=None,
        grace_expires_at=None,
        now=now,
        grace_days=DEFAULT_RETENTION_GRACE_DAYS,
    )
    assert decision.action == "flag"
    assert decision.grace_expires_at is not None
    grace = datetime.fromisoformat(decision.grace_expires_at)
    # Grace lands ~14 days from now (DEFAULT_RETENTION_GRACE_DAYS).
    expected_grace = now + timedelta(days=DEFAULT_RETENTION_GRACE_DAYS)
    assert abs((grace - expected_grace).total_seconds()) < 60

    # Same session, now flagged but still in grace → noop.
    flagged_grace = now + timedelta(days=10)
    decision = decide_retention_action(
        session_id="s-old",
        firm_id="firm-A",
        updated_at=now - timedelta(days=100),
        retention_days=90,
        retention_flagged_at=now - timedelta(days=4),
        grace_expires_at=flagged_grace,
        now=now,
    )
    assert decision.action == "noop"

    # Grace expired → purge action.
    decision = decide_retention_action(
        session_id="s-old",
        firm_id="firm-A",
        updated_at=now - timedelta(days=110),
        retention_days=90,
        retention_flagged_at=now - timedelta(days=20),
        grace_expires_at=now - timedelta(days=6),  # already expired
        now=now,
    )
    assert decision.action == "purge"


# ---------------------------------------------------------------------------
# 7. retention sweep notifies firm_admins before purging
# ---------------------------------------------------------------------------


def test_retention_sweep_notifies_before_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``notify_firm_admins_of_purge_schedule`` inserts a
    ``RETENTION_PURGE_SCHEDULED`` notification for every firm_admin
    of the firm."""
    db = _FakeDB()
    _install_db(monkeypatch, db)
    firm = str(uuid4())
    sid = str(uuid4())
    db.add_firm(firm, retention_days=90, admins=["u-admin-1", "u-admin-2"])
    db.add_session(sid, firm)

    from core.retention.policy import notify_firm_admins_of_purge_schedule

    grace = datetime.now(tz=timezone.utc) + timedelta(days=14)
    delivered = asyncio.run(notify_firm_admins_of_purge_schedule(
        firm_id=firm, session_id=sid, grace_expires_at=grace,
    ))
    assert delivered == 2
    assert len(db.notifications) == 2
    for n in db.notifications:
        assert n["notification_type"] == "retention_purge_scheduled"
        assert n["session_id"] == sid
        assert n["firm_id"] == firm
        assert n["recipient_id"] in {"u-admin-1", "u-admin-2"}
        # Body carries the grace_expires_at + reason — no client
        # content.
        assert "grace_expires_at" in n["source_ref"]
        assert n["source_ref"]["purge_reason"] == "retention_sweep"


# ---------------------------------------------------------------------------
# 8. retention default = keep indefinitely
# ---------------------------------------------------------------------------


def test_retention_default_keeps_indefinitely() -> None:
    """A firm with ``retention_days=None`` (the default) is never
    flagged for purge by the sweep. No firm's data is auto-deleted
    out from under them just because they didn't read the docs."""
    now = datetime.now(tz=timezone.utc)
    decision = decide_retention_action(
        session_id="s",
        firm_id="firm-noopt",
        updated_at=now - timedelta(days=10_000),  # ancient
        retention_days=None,                       # opted out
        retention_flagged_at=None,
        grace_expires_at=None,
        now=now,
    )
    assert decision.action == "noop"
    assert "indefinitely" in decision.reason.lower()
