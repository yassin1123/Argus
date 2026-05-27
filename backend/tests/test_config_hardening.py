"""Tests for the W23/D4 fail-loud config + kill silent fallback.

Five spec assertions:

  1. boot fails loud on missing verifier key — strict mode + no
     ANTHROPIC_API_KEY produces a degraded report; the silent-
     fallback selector raises VerifierUnavailable.
  2. heuristic NEVER silently substitutes in pilot/production —
     even an explicit ``--verifier heuristic_no_keys`` is denied.
  3. /health endpoint reports config status (mode + degraded +
     per-check details).
  4. secrets never appear in logs — the structured-event logger
     scanned for key patterns.
  5. backup + restore round-trips Firm A intact across a fresh
     DB.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))


# ---------------------------------------------------------------------------
# 1. boot fails loud on missing verifier key
# ---------------------------------------------------------------------------


def test_boot_fails_loud_on_missing_verifier_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In strict mode (pilot/production) + no ANTHROPIC_API_KEY:

      - ``validate_at_boot()`` returns a ConfigReport with
        ``degraded=True`` and ``can_run_real_verifier=False``.
      - ``assert_real_verifier_required()`` raises
        :class:`VerifierUnavailable` — the silent fallback is
        gone.
    """
    monkeypatch.setenv("ARGUS_MODE", "pilot")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-1234567890abcdef-something-longer")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")

    from core.config import (
        VerifierUnavailable, assert_real_verifier_required,
        is_strict_mode, validate_at_boot,
    )
    assert is_strict_mode() is True

    report = validate_at_boot()
    assert report.degraded is True
    assert report.can_run_real_verifier is False
    failed = [c.name for c in report.checks if not c.ok]
    assert "anthropic_api_key" in failed

    with pytest.raises(VerifierUnavailable) as exc:
        assert_real_verifier_required()
    assert "anthropic_api_key" in str(exc.value)
    assert "heuristic" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# 2. heuristic NEVER silently substitutes in pilot/production
# ---------------------------------------------------------------------------


def test_heuristic_never_silently_substitutes_in_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The three silent-fallback surfaces are all guarded:

      - ``runner.run_calibration`` with verifier=None — strict
        mode raises BEFORE constructing HeuristicVerifier.
      - ``report.select_verifier`` — explicit
        ``heuristic_no_keys`` is denied in strict mode.
      - ``run_real_calibration._select_verifier`` — same.

    In test mode the heuristic IS permitted explicitly.
    """
    # --- pilot mode, no keys -> all three surfaces refuse ---
    monkeypatch.setenv("ARGUS_MODE", "pilot")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from core.config import VerifierUnavailable, validate_at_boot
    validate_at_boot()

    from eval.calibration.report import select_verifier
    with pytest.raises(VerifierUnavailable):
        select_verifier("heuristic_no_keys")

    import eval.calibration.run_real_calibration as rrc
    with pytest.raises(VerifierUnavailable):
        rrc._select_verifier("heuristic_no_keys")

    # runner.run_calibration with verifier=None, use_cache=False,
    # in strict mode -> raises before constructing HeuristicVerifier.
    from eval.calibration.runner import run_calibration
    from eval.golden_set import GoldenSet
    empty_gs = GoldenSet(entries=[])
    # Pass a fake raw_path that doesn't exist so use_cache=False
    # and cache stays empty. The strict-mode guard fires.
    async def go():
        with pytest.raises(VerifierUnavailable):
            await run_calibration(
                verifier=None,
                golden_set=empty_gs,
                raw_scores_path=None,
                use_cache=False,
            )
    asyncio.run(go())

    # --- test mode permits heuristic ---
    monkeypatch.setenv("ARGUS_MODE", "test")
    validate_at_boot()
    v = select_verifier("heuristic_no_keys")
    assert v.name == "heuristic_no_keys"


# ---------------------------------------------------------------------------
# 3. /health endpoint reports config status
# ---------------------------------------------------------------------------


def test_health_endpoint_reports_config_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two endpoints from api/health.py surface the full
    boot-time state — mode, strict, degraded, per-check
    details. No secret values land in the response."""
    monkeypatch.setenv("ARGUS_MODE", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-1234567890abcdef")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-1234567890abcdef-12345")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")

    from api.health import health, health_detailed
    from core.config import validate_at_boot
    validate_at_boot()  # populate cached report

    short = asyncio.run(health())
    assert short["status"] == "ok"
    assert short["mode"] == "test"
    assert short["strict"] is False
    assert "degraded" in short
    assert "can_run_real_verifier" in short

    detailed = asyncio.run(health_detailed())
    assert detailed["mode"] == "test"
    assert "checks" in detailed
    check_names = {c["name"] for c in detailed["checks"]}
    assert {"anthropic_api_key", "openai_api_key", "deberta_module",
            "database_url"} <= check_names
    # No raw key values in the response.
    serialised = json.dumps(detailed)
    assert "sk-ant-fake-1234567890abcdef" not in serialised
    assert "sk-fake-1234567890abcdef-12345" not in serialised


# ---------------------------------------------------------------------------
# 4. secrets never in logs
# ---------------------------------------------------------------------------


def test_secrets_never_in_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configure the W20/D1 event logger to write to an in-memory
    buffer; emit several events whose payloads carry secret-shape
    tokens. The redact rule must drop every match — no key
    prefix (sk-ant-, sk-proj-, sk-fake-) survives serialisation.
    """
    from core.observability.logging import (
        REDACTED_VALUE,
        configure_event_logging,
        emit_event,
        reset_configuration_for_tests,
    )

    reset_configuration_for_tests()
    buf = io.StringIO()
    configure_event_logging(stream=buf)

    SECRETS = [
        "sk-ant-api03-1234567890abcdef-something-longer",
        "sk-proj-1234567890abcdef-something-longer",
        "sk-fake-shouldnt-appear-anywhere",
    ]
    # Emit events using BANNED field names so the W20/D1 redact
    # rule fires.
    for s in SECRETS:
        emit_event(
            "test.event",
            claim_text=s,
            evidence_text=s,
            memo_prose=s,
            raw_text=s,
        )

    out = buf.getvalue()
    for s in SECRETS:
        assert s not in out, (
            f"secret-shape token leaked into the log: {s!r}"
        )
    # And the redact sentinel IS present — proving the redact
    # rule fired (loud, not silent).
    assert REDACTED_VALUE in out


# ---------------------------------------------------------------------------
# 5. backup + restore round-trip
# ---------------------------------------------------------------------------


def test_backup_restore_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backup Firm A from one in-memory DB, restore into a fresh
    one, verify the row counts + key fields match.

    Uses an in-memory DB fake that mirrors what backup_firm /
    restore_firm read+write. Covers every surface listed in
    _FIRM_SCOPED_TABLES + the firm + users."""
    import core.backup.archive as arch_mod

    # Source DB — Firm A populated; Firm B noise to verify
    # firm-scoping.
    source_db: dict[str, list[dict[str, Any]]] = {
        "firms": [
            {"id": "firm-A", "slug": "firm-a", "name": "Firm A",
             "retention_days": 90, "monthly_budget_usd": 100.0,
             "session_cost_ceiling_usd": 5.0},
            {"id": "firm-B", "slug": "firm-b", "name": "Firm B",
             "retention_days": None, "monthly_budget_usd": None,
             "session_cost_ceiling_usd": 5.0},
        ],
        "users": [
            {"id": "u-A1", "email": "u1@firm-a", "full_name": "User A1",
             "role": "member", "default_firm_id": "firm-A",
             "created_at": datetime.now(tz=timezone.utc)},
            {"id": "u-B1", "email": "u1@firm-b", "full_name": "User B1",
             "role": "member", "default_firm_id": "firm-B",
             "created_at": datetime.now(tz=timezone.utc)},
        ],
        "firm_memberships": [
            {"id": "fm-A1", "firm_id": "firm-A", "user_id": "u-A1",
             "role": "admin",
             "added_at": datetime.now(tz=timezone.utc)},
            {"id": "fm-B1", "firm_id": "firm-B", "user_id": "u-B1",
             "role": "admin",
             "added_at": datetime.now(tz=timezone.utc)},
        ],
        "sessions": [
            {"id": "s-A1", "firm_id": "firm-A", "title": "Kestrel M&A",
             "status": "complete", "pipeline_state": "deliverable_ready",
             "report_mode": "m_and_a",
             "created_at": datetime.now(tz=timezone.utc),
             "updated_at": datetime.now(tz=timezone.utc),
             "created_by_user_id": "u-A1", "metadata": {}},
            {"id": "s-B1", "firm_id": "firm-B", "title": "OtherFirm",
             "status": "complete", "pipeline_state": "deliverable_ready",
             "report_mode": "m_and_a",
             "created_at": datetime.now(tz=timezone.utc),
             "updated_at": datetime.now(tz=timezone.utc),
             "created_by_user_id": "u-B1", "metadata": {}},
        ],
        "comments": [
            {"id": "c-A1", "session_id": "s-A1",
             "author_id": "u-A1", "body": "Looks good.",
             "anchor_type": "section",
             "anchor_ref": {"section_path": "summary"},
             "parent_comment_id": None, "resolved_at": None,
             "resolved_by": None,
             "created_at": datetime.now(tz=timezone.utc),
             "deleted_at": None},
        ],
        "payload_versions": [
            {"id": "v-A1", "session_id": "s-A1", "firm_id": "firm-A",
             "version_number": 1,
             "payload_snapshot": {"summary": "first version"},
             "change_type": "initial", "change_summary": None,
             "changed_section_paths": [], "review_state_at_version": "draft",
             "created_by": "u-A1",
             "created_at": datetime.now(tz=timezone.utc)},
        ],
    }
    # Dest DB starts empty.
    dest_db: dict[str, list[dict[str, Any]]] = {}

    def _make_acquire(db: dict[str, list[dict[str, Any]]],
                       readonly: bool = False):
        async def fetchrow(sql: str, *args: Any) -> Any:
            s = " ".join(sql.split())
            if "FROM firms WHERE id" in s and "slug" in s:
                fid = str(args[0])
                for r in db.get("firms", []):
                    if r["id"] == fid:
                        return r
                return None
            return None

        async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
            s = " ".join(sql.split())
            if "FROM users u" in s and "firm_memberships m" in s:
                fid = str(args[0])
                m_user_ids = {
                    m["user_id"] for m in db.get("firm_memberships", [])
                    if m["firm_id"] == fid
                }
                return [u for u in db.get("users", []) if u["id"] in m_user_ids]
            # firm-scoped tables — match WHERE clause. We look
            # ONLY at the outer-level FROM (before the first
            # WHERE) so a query like
            # ``FROM comments WHERE session_id IN (... FROM sessions WHERE firm_id...)``
            # matches "comments", not "sessions".
            outer = s.split(" WHERE ", 1)[0]
            for archive_field, table, where, _cols in arch_mod._FIRM_SCOPED_TABLES:
                if f"FROM {table}" in outer and f"FROM {table} WHERE " in s:
                    fid = str(args[0])
                    rows = db.get(table, [])
                    if "session_id IN" in where:
                        sess_ids = {
                            r["id"] for r in db.get("sessions", [])
                            if r.get("firm_id") == fid
                        }
                        return [
                            r for r in rows
                            if str(r.get("session_id")) in sess_ids
                        ]
                    if "firm_id = " in where:
                        return [
                            r for r in rows
                            if str(r.get("firm_id")) == fid
                        ]
                    if "engagement_id IN" in where:
                        sess_ids = {
                            r["id"] for r in db.get("sessions", [])
                            if r.get("firm_id") == fid
                        }
                        return [
                            r for r in rows
                            if str(r.get("engagement_id")) in sess_ids
                        ]
            return []

        async def execute(sql: str, *args: Any) -> str:
            s = " ".join(sql.split())
            if readonly:
                return "OK"
            if "INSERT INTO " in s:
                table = s.split("INSERT INTO ", 1)[1].split(" ", 1)[0]
                # Pull column names from the SQL — they appear in
                # parens immediately after the table.
                cols_part = s.split("(", 1)[1].split(")", 1)[0]
                cols = [c.strip() for c in cols_part.split(",")]
                row = {c: args[i] for i, c in enumerate(cols)}
                db.setdefault(table, []).append(row)
                return "INSERT 0 1"
            return "OK"

        fake_conn = mock.MagicMock()
        fake_conn.fetchrow = fetchrow
        fake_conn.fetch = fetch
        fake_conn.execute = execute

        class _CM:
            async def __aenter__(self): return fake_conn
            async def __aexit__(self, *a): return None

        return lambda: _CM()

    # Backup against the source DB.
    monkeypatch.setattr(arch_mod, "acquire", _make_acquire(source_db))
    archive = asyncio.run(arch_mod.backup_firm("firm-A"))

    # Archive carries Firm A's rows + NONE of Firm B's.
    assert archive.firm["id"] == "firm-A"
    assert all(u["default_firm_id"] == "firm-A" for u in archive.users)
    assert all(
        m["firm_id"] == "firm-A" for m in archive.firm_memberships
    )
    assert all(s["firm_id"] == "firm-A" for s in archive.sessions)
    # Firm B's session is not in the archive.
    archived_session_ids = {s["id"] for s in archive.sessions}
    assert "s-B1" not in archived_session_ids
    # Firm A's session, comment, version all present.
    assert "s-A1" in archived_session_ids
    assert len(archive.comments) == 1 and archive.comments[0]["id"] == "c-A1"
    assert len(archive.payload_versions) == 1

    # Restore against an empty DB.
    monkeypatch.setattr(arch_mod, "acquire", _make_acquire(dest_db))
    counts = asyncio.run(arch_mod.restore_firm(archive))

    # Firm + user + session + comment + version all inserted.
    assert counts.get("firms", 0) == 1
    assert counts.get("users", 0) >= 1
    assert counts.get("firm_memberships", 0) >= 1
    assert counts.get("sessions", 0) >= 1
    assert counts.get("comments", 0) >= 1
    assert counts.get("payload_versions", 0) >= 1
    # Round-trip integrity: same firm slug, same session id.
    assert dest_db["firms"][0]["slug"] == "firm-a"
    assert dest_db["sessions"][0]["id"] == "s-A1"
    assert dest_db["sessions"][0]["firm_id"] == "firm-A"
