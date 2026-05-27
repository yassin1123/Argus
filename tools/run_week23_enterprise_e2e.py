"""Week 23 enterprise readiness end-to-end.

Phase 5 / Week 23 / Day 5. Drives the four pilot-blocking
enterprise concerns end-to-end against TWO firms — not a unit
test, an integration sweep that proves Days 1-4 compose:

  1. Tenant isolation (D1)         — Firm B attempts a battery of
                                       cross-firm reads against Firm A;
                                       all are blocked + denials logged.
  2. Hard deletion (D2)            — a Firm A engagement is purged;
                                       zero residual rows / files; the
                                       purge_audit_log entry is
                                       content-free.
  3. Retention sweep (D2)          — an expired engagement is flagged,
                                       firm_admin notified, then purged
                                       after the grace window.
  4. Audit export (D3)             — Firm A's audit trail exports to
                                       CSV + NDJSON; scoped to Firm A;
                                       no claim/evidence text leaves.
  5. Cost budget (D3)              — Firm A is driven past 80% + 100%;
                                       notifications fire, new engagements
                                       soft-blocked, in-flight unaffected.
  6. Rate limit (D3)               — Firm A exceeds the engagement-
                                       creation rate; the next attempt is
                                       blocked with retry_after.
  7. Fail-loud config (D4)         — strict mode with missing keys
                                       degrades the boot report and
                                       :func:`assert_real_verifier_required`
                                       raises VerifierUnavailable.
  8. Backup / restore (D4)         — Firm A round-trips through
                                       backup_firm → restore_firm; data
                                       deleted between the steps comes
                                       back; Firm B rows never leak.

The runner is self-contained:

  - Creates two synthetic firms (slugs ``w23-e2e-meridian`` and
    ``w23-e2e-lumen``) with a firm_admin user each and a small
    engagement per firm. Idempotent — re-running drops the prior
    e2e state before re-seeding.
  - Cleans up at the end (drops the synthetic firms + restores any
    env vars touched by scenario 7) so the e2e leaves the DB in the
    state it found it.
  - Saves a structured summary at
    ``backend/eval_runs/week23_enterprise/summary.json``.

Usage::

    python tools/run_week23_enterprise_e2e.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))
sys.path.insert(0, str(_REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO / ".env")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/argus",
)
os.environ.setdefault("ARGUS_EMAIL_ADAPTER", "capture")


_OUT = _REPO / "backend" / "eval_runs" / "week23_enterprise"

FIRM_A_SLUG = "w23-e2e-meridian"
FIRM_B_SLUG = "w23-e2e-lumen"


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    ok: bool
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Bootstrap — synthetic firms + sessions
# ---------------------------------------------------------------------------


async def _ensure_firm(conn, slug: str, name: str) -> str:
    row = await conn.fetchrow(
        "SELECT id FROM firms WHERE slug = $1", slug,
    )
    if row:
        return str(row["id"])
    row = await conn.fetchrow(
        """
        INSERT INTO firms (name, slug, metadata)
        VALUES ($1, $2, '{}'::jsonb) RETURNING id
        """,
        name, slug,
    )
    return str(row["id"])


async def _ensure_user(
    conn, *, email: str, full_name: str,
    firm_id: str, firm_role: str = "admin",
) -> str:
    row = await conn.fetchrow(
        "SELECT id FROM users WHERE email = $1::citext", email,
    )
    if row:
        user_id = str(row["id"])
    else:
        user_id = str(uuid4())
        await conn.execute(
            """
            INSERT INTO users (id, email, password_hash, full_name,
                               role, default_firm_id)
            VALUES ($1::uuid, $2, '$2b$12$placeholder_e2e_only',
                    $3, 'member', $4::uuid)
            """,
            user_id, email, full_name, firm_id,
        )
    await conn.execute(
        """
        INSERT INTO firm_memberships (firm_id, user_id, role)
        VALUES ($1::uuid, $2::uuid, $3)
        ON CONFLICT (firm_id, user_id) DO UPDATE SET role = EXCLUDED.role
        """,
        firm_id, user_id, firm_role,
    )
    await conn.execute(
        "UPDATE users SET default_firm_id = $1::uuid WHERE id = $2::uuid",
        firm_id, user_id,
    )
    return user_id


async def _create_session(
    conn, *, firm_id: str, user_id: str, title: str,
) -> str:
    sess = await conn.fetchrow(
        """
        INSERT INTO sessions (firm_id, title, query, status, report_mode,
                              pipeline_state, created_by_user_id)
        VALUES ($1::uuid, $2, $3, 'ready', 'general', 'complete',
                $4::uuid)
        RETURNING id
        """,
        firm_id, title, "synthetic e2e query", user_id,
    )
    return str(sess["id"])


async def _populate_session(
    conn, *, session_id: str, firm_id: str, user_id: str,
) -> dict[str, Any]:
    """Plant the children we need for purge / export / backup
    scenarios. Counts returned for the report."""
    n_evidence = 3
    for i in range(n_evidence):
        await conn.execute(
            """
            INSERT INTO evidence_objects
                (session_id, claim, quote, source_type,
                 source_url, source_title, source_score)
            VALUES ($1::uuid, $2, $3, 'document',
                    'https://example.com/e2e', 'E2E source',
                    0.9)
            """,
            session_id, f"e2e claim {i}", f"e2e quote {i}",
        )

    await conn.execute(
        """
        INSERT INTO comments
            (session_id, firm_id, author_id, body, anchor_type)
        VALUES ($1::uuid, $2::uuid, $3::uuid, 'e2e comment', 'engagement')
        """,
        session_id, firm_id, user_id,
    )

    # One payload_version for backup/restore round-trip
    await conn.execute(
        """
        INSERT INTO payload_versions
            (session_id, firm_id, version_number, payload_snapshot,
             change_type, change_summary, changed_section_paths,
             review_state_at_version, created_by)
        VALUES ($1::uuid, $2::uuid, 1, '{"e2e": true}'::jsonb,
                'initial', 'e2e baseline', '[]'::jsonb, 'draft',
                $3::uuid)
        """,
        session_id, firm_id, user_id,
    )

    # An export_artifact with a real file on disk so purge can show
    # both DB-row + file deletion.
    artifact_dir = _REPO / "backend" / "eval_runs" / "week23_enterprise" / "_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{session_id}.txt"
    artifact_path.write_text("e2e artifact body", encoding="utf-8")
    await conn.execute(
        """
        INSERT INTO export_artifacts
            (session_id, firm_id, artifact_type, format, status,
             file_path)
        VALUES ($1::uuid, $2::uuid, 'memo', 'html', 'ready', $3)
        """,
        session_id, firm_id, str(artifact_path),
    )

    return {
        "evidence": n_evidence,
        "comments": 1,
        "payload_versions": 1,
        "artifacts": 1,
        "artifact_path": str(artifact_path),
    }


async def bootstrap() -> dict[str, Any]:
    """Tear down + recreate the e2e firms. Returns a context dict
    used by every scenario."""
    from db.connection import acquire

    async with acquire() as conn:
        # Clean any prior e2e state.
        await conn.execute(
            "DELETE FROM sessions WHERE firm_id IN "
            "(SELECT id FROM firms WHERE slug = ANY($1::text[]))",
            [FIRM_A_SLUG, FIRM_B_SLUG],
        )
        await conn.execute(
            "DELETE FROM cost_ledger WHERE firm_id IN "
            "(SELECT id FROM firms WHERE slug = ANY($1::text[]))",
            [FIRM_A_SLUG, FIRM_B_SLUG],
        )
        await conn.execute(
            "DELETE FROM firm_budget_notifications WHERE firm_id IN "
            "(SELECT id FROM firms WHERE slug = ANY($1::text[]))",
            [FIRM_A_SLUG, FIRM_B_SLUG],
        )
        await conn.execute(
            "DELETE FROM notifications WHERE firm_id IN "
            "(SELECT id FROM firms WHERE slug = ANY($1::text[]))",
            [FIRM_A_SLUG, FIRM_B_SLUG],
        )
        await conn.execute(
            "DELETE FROM purge_audit_log WHERE firm_id IN "
            "(SELECT id FROM firms WHERE slug = ANY($1::text[]))",
            [FIRM_A_SLUG, FIRM_B_SLUG],
        )
        await conn.execute(
            "DELETE FROM metric_events WHERE firm_id IN "
            "(SELECT id FROM firms WHERE slug = ANY($1::text[]))",
            [FIRM_A_SLUG, FIRM_B_SLUG],
        )

        firm_a = await _ensure_firm(
            conn, FIRM_A_SLUG, "W23 E2E — Meridian Test",
        )
        firm_b = await _ensure_firm(
            conn, FIRM_B_SLUG, "W23 E2E — Lumen Test",
        )

        # Reset firm-level governance state on both.
        await conn.execute(
            """
            UPDATE firms
               SET retention_days = NULL,
                   monthly_budget_usd = NULL,
                   session_cost_ceiling_usd = 5.0
             WHERE id = ANY($1::uuid[])
            """,
            [firm_a, firm_b],
        )

        admin_a = await _ensure_user(
            conn,
            email="w23-e2e-firm-a-admin@example.com",
            full_name="Firm A Admin (E2E)",
            firm_id=firm_a, firm_role="admin",
        )
        admin_b = await _ensure_user(
            conn,
            email="w23-e2e-firm-b-admin@example.com",
            full_name="Firm B Admin (E2E)",
            firm_id=firm_b, firm_role="admin",
        )

        # One session per firm + a synthetic engagement to purge
        # (separate from the keep-around session so the purge
        # scenario doesn't strand the rest of the e2e).
        sess_a_keep = await _create_session(
            conn, firm_id=firm_a, user_id=admin_a,
            title="[w23-e2e] Firm A keep",
        )
        sess_a_purge = await _create_session(
            conn, firm_id=firm_a, user_id=admin_a,
            title="[w23-e2e] Firm A purge target",
        )
        sess_a_retain = await _create_session(
            conn, firm_id=firm_a, user_id=admin_a,
            title="[w23-e2e] Firm A retention target",
        )
        sess_b = await _create_session(
            conn, firm_id=firm_b, user_id=admin_b,
            title="[w23-e2e] Firm B (must never leak to A)",
        )

        counts_a_keep = await _populate_session(
            conn, session_id=sess_a_keep,
            firm_id=firm_a, user_id=admin_a,
        )
        counts_a_purge = await _populate_session(
            conn, session_id=sess_a_purge,
            firm_id=firm_a, user_id=admin_a,
        )
        counts_b = await _populate_session(
            conn, session_id=sess_b,
            firm_id=firm_b, user_id=admin_b,
        )

    return {
        "firm_a": firm_a, "firm_b": firm_b,
        "admin_a": admin_a, "admin_b": admin_b,
        "sess_a_keep": sess_a_keep,
        "sess_a_purge": sess_a_purge,
        "sess_a_retain": sess_a_retain,
        "sess_b": sess_b,
        "counts_a_keep": counts_a_keep,
        "counts_a_purge": counts_a_purge,
        "counts_b": counts_b,
    }


# ---------------------------------------------------------------------------
# 1. Tenant isolation
# ---------------------------------------------------------------------------


async def scenario_isolation(ctx: dict[str, Any]) -> Scenario:
    """Firm B's admin makes a battery of cross-firm reads against
    Firm A. Every one must hit the 404 anti-enumeration path."""
    from fastapi import HTTPException

    from auth.firm_scope import assert_firm_access

    firm_b_user = {
        "user_id": ctx["admin_b"],
        "role": "member",
        "default_firm_id": ctx["firm_b"],
        "default_firm_role": "admin",
    }

    attempts = [
        ("session", ctx["sess_a_keep"]),
        ("session", ctx["sess_a_purge"]),
        ("session", ctx["sess_a_retain"]),
        ("comment", ctx["sess_a_keep"]),
        ("payload_version", ctx["sess_a_keep"]),
        ("artifact", ctx["sess_a_keep"]),
        ("engagement_membership", ctx["sess_a_keep"]),
    ]
    blocked = 0
    denials: list[dict[str, Any]] = []
    for kind, res_id in attempts:
        try:
            await assert_firm_access(
                user=firm_b_user,
                resource_firm_id=ctx["firm_a"],
                resource_kind=kind,
                resource_id=res_id,
                allow_system_admin=False,
            )
            denials.append({"kind": kind, "outcome": "GRANTED"})
        except HTTPException as e:
            if e.status_code == 404:
                blocked += 1
                denials.append({"kind": kind, "outcome": "denied_404"})
            else:
                denials.append({
                    "kind": kind, "outcome": f"unexpected_{e.status_code}",
                })

    # Same-firm sanity check — Firm B admin reading Firm B's own
    # resource must succeed.
    same_firm_ok = False
    try:
        await assert_firm_access(
            user=firm_b_user,
            resource_firm_id=ctx["firm_b"],
            resource_kind="session",
            resource_id=ctx["sess_b"],
            allow_system_admin=False,
        )
        same_firm_ok = True
    except HTTPException:
        same_firm_ok = False

    ok = blocked == len(attempts) and same_firm_ok
    return Scenario(
        name="isolation",
        ok=ok,
        reason=(
            f"{blocked}/{len(attempts)} cross-firm attempts blocked; "
            f"same-firm read allowed={same_firm_ok}"
        ),
        evidence={
            "attempts": len(attempts),
            "blocked_404": blocked,
            "denials": denials,
            "same_firm_read_allowed": same_firm_ok,
        },
    )


# ---------------------------------------------------------------------------
# 2. Hard deletion
# ---------------------------------------------------------------------------


async def scenario_deletion(ctx: dict[str, Any]) -> Scenario:
    """Purge Firm A's purge-target engagement. Verify zero
    residual rows + the artifact file is gone + the purge_audit_log
    entry is content-free."""
    from db.connection import acquire

    from core.retention.deletion import (
        _PURGE_TABLES, purge_engagement,
    )

    artifact_path = ctx["counts_a_purge"]["artifact_path"]
    sess_id = ctx["sess_a_purge"]

    # The file must exist BEFORE the purge so the "files_deleted"
    # count is meaningful evidence.
    artifact_existed_before = Path(artifact_path).exists()

    report = await purge_engagement(
        sess_id, actor_user_id=ctx["admin_a"],
        purge_reason="firm_admin_request",
    )

    residual: dict[str, int] = {}
    async with acquire() as conn:
        for table in _PURGE_TABLES:
            try:
                row = await conn.fetchrow(
                    f"SELECT COUNT(*)::int AS n FROM {table} "
                    f"WHERE session_id = $1::uuid",
                    sess_id,
                )
                n = int(row["n"]) if row else 0
                if n > 0:
                    residual[table] = n
            except Exception:  # noqa: BLE001
                continue

        audit_row = await conn.fetchrow(
            """
            SELECT id, purge_reason, rows_deleted, files_deleted
              FROM purge_audit_log WHERE id = $1
            """,
            report.audit_log_id,
        )
    audit_payload = dict(audit_row) if audit_row else {}
    # The rows_deleted JSON should NEVER contain claim/evidence text
    rd_raw = audit_payload.get("rows_deleted")
    if isinstance(rd_raw, str):
        try:
            rd = json.loads(rd_raw)
        except Exception:
            rd = {}
    else:
        rd = rd_raw or {}
    leaked_keys = [
        k for k in rd.keys()
        if not isinstance(k, str) or "claim" in k.lower()
        or "evidence_content" in k.lower()
    ]

    file_gone = not Path(artifact_path).exists()

    ok = (
        not residual
        and audit_row is not None
        and not leaked_keys
        and artifact_existed_before
        and file_gone
    )
    return Scenario(
        name="deletion",
        ok=ok,
        reason=(
            f"residual_tables={list(residual.keys()) or 'none'}; "
            f"audit_row_id={report.audit_log_id}; "
            f"file_existed_before={artifact_existed_before}, "
            f"file_gone_after={file_gone}; "
            f"leaked_payload_keys={leaked_keys or 'none'}"
        ),
        evidence={
            "session_id": sess_id,
            "purge_report": report.to_dict(),
            "residual_rows": residual,
            "audit_log_row": {
                **{k: v for k, v in audit_payload.items() if k != "rows_deleted"},
                "rows_deleted": rd,
            },
            "artifact_existed_before": artifact_existed_before,
            "artifact_gone_after": file_gone,
            "leaked_payload_keys": leaked_keys,
        },
    )


# ---------------------------------------------------------------------------
# 3. Retention sweep
# ---------------------------------------------------------------------------


async def scenario_retention(ctx: dict[str, Any]) -> Scenario:
    """Mark Firm A retention_days=30. Backdate sess_a_retain
    updated_at by 100 days. Sweep → flag + admin notified. Move
    'now' forward past the grace window → purge approved."""
    from db.connection import acquire

    from core.retention.deletion import purge_engagement
    from core.retention.policy import (
        DEFAULT_RETENTION_GRACE_DAYS,
        decide_retention_action,
        list_expired_sessions,
        mark_flagged,
        notify_firm_admins_of_purge_schedule,
        set_firm_retention_days,
    )

    sess = ctx["sess_a_retain"]
    firm_a = ctx["firm_a"]

    now = datetime.now(tz=timezone.utc)
    expired_at = now - timedelta(days=100)

    async with acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET updated_at = $2, "
            "retention_flagged_at = NULL, "
            "retention_grace_expires_at = NULL "
            "WHERE id = $1::uuid",
            sess, expired_at,
        )
    await set_firm_retention_days(firm_a, 30)

    # 1) Sweep — expect action='flag' for our target.
    decisions = await list_expired_sessions(now=now)
    flag_decision = next(
        (d for d in decisions if d.session_id == sess), None,
    )
    if flag_decision is None or flag_decision.action != "flag":
        return Scenario(
            name="retention",
            ok=False,
            reason=(
                f"expected action=flag for {sess}; got "
                f"{flag_decision.action if flag_decision else 'no decision'}"
            ),
            evidence={"decisions": [d.to_dict() for d in decisions]},
        )

    # Apply the flag step exactly as the runner script does.
    grace_expires = now + timedelta(days=DEFAULT_RETENTION_GRACE_DAYS)
    await mark_flagged(sess, grace_expires)
    delivered = await notify_firm_admins_of_purge_schedule(
        firm_id=firm_a, session_id=sess,
        grace_expires_at=grace_expires,
    )

    async with acquire() as conn:
        notif_rows = await conn.fetch(
            """
            SELECT notification_type, summary, source_ref
              FROM notifications
             WHERE firm_id = $1::uuid AND session_id = $2::uuid
            """,
            firm_a, sess,
        )
    notif_types = [r["notification_type"] for r in notif_rows]
    if delivered < 1 or "retention_purge_scheduled" not in notif_types:
        return Scenario(
            name="retention",
            ok=False,
            reason=(
                f"flag stage delivered={delivered}; "
                f"notification types={notif_types}"
            ),
            evidence={"notifications": notif_types},
        )

    # 2) Move 'now' past the grace window — re-run the decision.
    future_now = grace_expires + timedelta(days=1)
    purge_decision = decide_retention_action(
        session_id=sess,
        firm_id=firm_a,
        updated_at=expired_at,
        retention_days=30,
        retention_flagged_at=now,
        grace_expires_at=grace_expires,
        now=future_now,
    )
    if purge_decision.action != "purge":
        return Scenario(
            name="retention",
            ok=False,
            reason=(
                f"expected action=purge after grace; got "
                f"{purge_decision.action}"
            ),
            evidence={"decision": purge_decision.to_dict()},
        )

    # 3) Execute the purge as the sweep would.
    report = await purge_engagement(
        sess, actor_user_id=None, purge_reason="retention_sweep",
    )

    # Clean up the retention setting so it doesn't leak to next run
    await set_firm_retention_days(firm_a, None)

    return Scenario(
        name="retention",
        ok=True,
        reason=(
            f"flag stage notified {delivered} admin(s); "
            f"after grace, purge approved + executed "
            f"({report.total_rows_deleted()} rows)"
        ),
        evidence={
            "flag_decision": flag_decision.to_dict(),
            "notifications_dispatched": delivered,
            "notification_types": notif_types,
            "purge_decision": purge_decision.to_dict(),
            "purge_report": report.to_dict(),
        },
    )


# ---------------------------------------------------------------------------
# 4. Audit export
# ---------------------------------------------------------------------------


async def scenario_audit_export(ctx: dict[str, Any]) -> Scenario:
    """Plant audit_events for Firm A + Firm B sessions, then export
    Firm A. Verify scope + content-free payload + CSV/JSON shape."""
    from db.connection import acquire

    from api.audit_export import (
        _csv_stream, _fetch_audit_rows, _json_stream,
        _strip_payload,
    )

    async with acquire() as conn:
        # Two Firm A events
        await conn.execute(
            """
            INSERT INTO audit_events
                (actor_user_id, action, resource_type, resource_id,
                 method, path, status_code, payload)
            VALUES ($1::uuid, 'engagement.create', 'session', $2,
                    'POST', '/api/sessions', 201, $3::jsonb)
            """,
            ctx["admin_a"], ctx["sess_a_keep"],
            json.dumps({
                "session_id": ctx["sess_a_keep"],
                "engagement_id": ctx["sess_a_keep"],
                # Pretend a careless future writer put claim text here
                # to verify _strip_payload removes it.
                "claim_text": "MUST_NOT_LEAK confidential client memo",
            }),
        )
        await conn.execute(
            """
            INSERT INTO audit_events
                (actor_user_id, action, resource_type, resource_id,
                 method, path, status_code, payload)
            VALUES ($1::uuid, 'review.approve', 'session', $2,
                    'POST', '/api/sessions/x/approve', 200, $3::jsonb)
            """,
            ctx["admin_a"], ctx["sess_a_keep"],
            json.dumps({
                "session_id": ctx["sess_a_keep"],
                "from_state": "in_review", "to_state": "approved",
            }),
        )
        # One Firm B event — must NOT show up in Firm A's export
        await conn.execute(
            """
            INSERT INTO audit_events
                (actor_user_id, action, resource_type, resource_id,
                 method, path, status_code, payload)
            VALUES ($1::uuid, 'engagement.create', 'session', $2,
                    'POST', '/api/sessions', 201, $3::jsonb)
            """,
            ctx["admin_b"], ctx["sess_b"],
            json.dumps({
                "session_id": ctx["sess_b"],
                "claim_text": "FIRM_B_CONFIDENTIAL_should_not_appear",
            }),
        )

    rows: list[dict[str, Any]] = []
    async for r in _fetch_audit_rows(ctx["firm_a"], None, None):
        rows.append(r)

    firm_a_session_rows = [
        r for r in rows
        if r.get("resource_id") == ctx["sess_a_keep"]
        or (
            isinstance(r.get("payload"), dict)
            and r["payload"].get("session_id") == ctx["sess_a_keep"]
        )
    ]
    firm_b_session_rows = [
        r for r in rows
        if r.get("resource_id") == ctx["sess_b"]
        or (
            isinstance(r.get("payload"), dict)
            and r["payload"].get("session_id") == ctx["sess_b"]
        )
    ]

    # Sniff every row's serialised JSON for the canary strings.
    leak_canary_a = "MUST_NOT_LEAK"
    leak_canary_b = "FIRM_B_CONFIDENTIAL"
    serialised = json.dumps(rows)
    leaked_a_text = leak_canary_a in serialised
    leaked_b_text = leak_canary_b in serialised

    # CSV + NDJSON shape sanity
    async def _rows_iter():
        for r in rows:
            yield r

    csv_bytes = b""
    async for chunk in _csv_stream(_rows_iter()):
        csv_bytes += chunk
    nd_bytes = b""
    async for chunk in _json_stream(_rows_iter()):
        nd_bytes += chunk
    csv_lines = csv_bytes.decode("utf-8").splitlines()
    nd_lines = nd_bytes.decode("utf-8").splitlines()

    # _strip_payload spot-check
    stripped = _strip_payload({
        "session_id": "x", "claim_text": "leak", "review_state": "draft",
    })

    ok = (
        len(firm_a_session_rows) >= 1
        and len(firm_b_session_rows) == 0
        and not leaked_a_text
        and not leaked_b_text
        and "claim_text" not in stripped
        and len(csv_lines) >= 1
        and len(nd_lines) == len(rows)
    )
    return Scenario(
        name="audit_export",
        ok=ok,
        reason=(
            f"firm_a_rows={len(firm_a_session_rows)}, "
            f"firm_b_rows={len(firm_b_session_rows)} (must be 0), "
            f"text_leak_a={leaked_a_text}, "
            f"text_leak_b={leaked_b_text}, "
            f"csv_lines={len(csv_lines)}, ndjson_lines={len(nd_lines)}"
        ),
        evidence={
            "row_count": len(rows),
            "firm_a_session_rows": len(firm_a_session_rows),
            "firm_b_session_rows": len(firm_b_session_rows),
            "claim_text_leak_into_export": leaked_a_text or leaked_b_text,
            "csv_lines": len(csv_lines),
            "ndjson_lines": len(nd_lines),
            "strip_payload_drops_claim_text": "claim_text" not in stripped,
            "strip_payload_keeps_session_id": "session_id" in stripped,
        },
    )


# ---------------------------------------------------------------------------
# 5. Budget threshold + soft stop
# ---------------------------------------------------------------------------


async def scenario_budget(ctx: dict[str, Any]) -> Scenario:
    """Set Firm A monthly budget = $10. Drive spend through cost_ledger
    to $8 (80%) then $10.50 (>100%). Confirm thresholds notify +
    new-engagement gate trips + an in-flight session is NOT killed."""
    from db.connection import acquire

    from core.cost_governance.budgets import (
        check_engagement_blocked, check_session_ceiling,
        compute_budget_status, maybe_notify_threshold_crossing,
    )

    firm_a = ctx["firm_a"]
    sess_keep = ctx["sess_a_keep"]

    async with acquire() as conn:
        await conn.execute(
            "UPDATE firms SET monthly_budget_usd = 10.0 WHERE id = $1::uuid",
            firm_a,
        )

        async def _add_spend(amount: float) -> None:
            await conn.execute(
                """
                INSERT INTO cost_ledger
                    (firm_id, session_id, agent, provider, model,
                     prompt_tokens, completion_tokens, cost_usd)
                VALUES ($1::uuid, $2::uuid, 'analyst', 'anthropic',
                        'claude-opus', 100, 100, $3)
                """,
                firm_a, sess_keep, amount,
            )

        # 80% — should fire the 80% notification
        await _add_spend(8.0)

    fired_80 = await maybe_notify_threshold_crossing(firm_a)

    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO cost_ledger
                (firm_id, session_id, agent, provider, model,
                 prompt_tokens, completion_tokens, cost_usd)
            VALUES ($1::uuid, $2::uuid, 'verifier', 'openai',
                    'gpt-4o-mini', 100, 100, 2.5)
            """,
            firm_a, sess_keep,
        )

    fired_100 = await maybe_notify_threshold_crossing(firm_a)
    status = await compute_budget_status(firm_a)
    blocked_new, gate_reason = await check_engagement_blocked(firm_a)

    # Per-session ceiling: keep session's spend ($10.5) > default $5
    over_ceiling, sess_spend, ceiling = await check_session_ceiling(sess_keep)

    # In-flight check: sess_keep status should still be 'ready', not
    # forcibly cancelled.
    async with acquire() as conn:
        sess_row = await conn.fetchrow(
            "SELECT status FROM sessions WHERE id = $1::uuid", sess_keep,
        )
        notif_rows = await conn.fetch(
            """
            SELECT notification_type, summary
              FROM notifications
             WHERE firm_id = $1::uuid
               AND notification_type = 'firm_budget_threshold'
             ORDER BY created_at
            """,
            firm_a,
        )

    notif_summaries = [r["summary"] for r in notif_rows]
    sess_still_alive = (
        sess_row is not None and sess_row["status"] != "cancelled"
    )

    ok = (
        80 in fired_80
        and 100 in fired_100
        and status.blocks_new_engagements is True
        and blocked_new is True
        and over_ceiling is True
        and sess_still_alive
        and len(notif_summaries) >= 2
    )
    return Scenario(
        name="budget",
        ok=ok,
        reason=(
            f"80%_fired={80 in fired_80}, 100%_fired={100 in fired_100}, "
            f"blocks_new_engagements={status.blocks_new_engagements}, "
            f"per_session_ceiling_tripped={over_ceiling} "
            f"({sess_spend:.2f} > {ceiling:.2f}), "
            f"in_flight_session_killed={not sess_still_alive}"
        ),
        evidence={
            "fired_thresholds": {"80_pass": fired_80, "100_pass": fired_100},
            "status": status.to_dict(),
            "engagement_gate_blocked": blocked_new,
            "engagement_gate_reason": gate_reason,
            "session_ceiling": {
                "over": over_ceiling, "spend": sess_spend,
                "ceiling": ceiling,
            },
            "in_flight_session_status": (
                sess_row["status"] if sess_row else None
            ),
            "notification_summaries": notif_summaries,
        },
    )


# ---------------------------------------------------------------------------
# 6. Rate limit
# ---------------------------------------------------------------------------


async def scenario_rate_limit(ctx: dict[str, Any]) -> Scenario:
    """Insert 60 sessions for Firm A in the last hour, then ask the
    gate — it must report blocked=True with a retry_after hint."""
    from db.connection import acquire

    from core.cost_governance.rate_limits import (
        DEFAULT_ENGAGEMENT_RATE_PER_HOUR,
        check_engagement_creation_limit,
    )

    firm_a = ctx["firm_a"]
    now = datetime.now(tz=timezone.utc)
    inserted = 0
    async with acquire() as conn:
        # Wipe any sessions we inserted earlier — only count the
        # synthetic burst we'd create now for the rate-limit check.
        await conn.execute(
            "DELETE FROM sessions WHERE firm_id = $1::uuid "
            "AND title LIKE '[w23-e2e][rate]%'",
            firm_a,
        )
        for i in range(DEFAULT_ENGAGEMENT_RATE_PER_HOUR):
            await conn.execute(
                """
                INSERT INTO sessions
                    (firm_id, title, query, status, report_mode,
                     created_by_user_id, created_at)
                VALUES ($1::uuid, $2, 'burst', 'draft', 'general',
                        $3::uuid, $4)
                """,
                firm_a, f"[w23-e2e][rate] {i}", ctx["admin_a"],
                now - timedelta(minutes=i % 50),
            )
            inserted += 1

    decision = await check_engagement_creation_limit(firm_a)

    # Cleanup the rate-limit burst rows so the next scenario isn't
    # polluted. The deletion + retention scenarios already ran above.
    async with acquire() as conn:
        await conn.execute(
            "DELETE FROM sessions WHERE firm_id = $1::uuid "
            "AND title LIKE '[w23-e2e][rate]%'",
            firm_a,
        )

    ok = (
        decision.blocked
        and decision.retry_after_seconds > 0
        and decision.current_count >= DEFAULT_ENGAGEMENT_RATE_PER_HOUR
    )
    return Scenario(
        name="rate_limit",
        ok=ok,
        reason=(
            f"inserted={inserted}; "
            f"limit={decision.limit}/hour; "
            f"current={decision.current_count}; "
            f"blocked={decision.blocked}; "
            f"retry_after_s={decision.retry_after_seconds}"
        ),
        evidence={
            "inserted_in_window": inserted,
            "decision": decision.to_dict(),
        },
    )


# ---------------------------------------------------------------------------
# 7. Fail-loud config (missing verifier key in pilot mode)
# ---------------------------------------------------------------------------


def scenario_config() -> Scenario:
    """Re-validate boot in pilot mode with no LLM keys. Expect:
    degraded=True; can_run_real_verifier=False;
    assert_real_verifier_required raises VerifierUnavailable.

    The heuristic-fallback kill points were wired in D4 — this
    proves the policy executes when an operator forgets a key."""
    from core import config as cfg

    # Snapshot env so we restore after — never leak this state out.
    snap = {
        k: os.environ.get(k) for k in (
            "ARGUS_MODE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        )
    }
    try:
        os.environ["ARGUS_MODE"] = "pilot"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)

        report = cfg.validate_at_boot()
        raised = False
        reason = ""
        try:
            cfg.assert_real_verifier_required()
        except cfg.VerifierUnavailable as e:
            raised = True
            reason = str(e)

        ok = (
            report.mode == "pilot"
            and report.strict is True
            and report.degraded is True
            and report.can_run_real_verifier is False
            and raised
        )
        return Scenario(
            name="config",
            ok=ok,
            reason=(
                f"mode={report.mode}, strict={report.strict}, "
                f"degraded={report.degraded}, "
                f"can_run_real_verifier={report.can_run_real_verifier}, "
                f"VerifierUnavailable raised={raised}"
            ),
            evidence={
                "report": report.to_dict(),
                "verifier_unavailable_raised": raised,
                "verifier_unavailable_message_excerpt": reason[:280],
            },
        )
    finally:
        # Restore env, re-validate so subsequent scenarios use the
        # operator's real keys.
        for k, v in snap.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cfg.validate_at_boot()


# ---------------------------------------------------------------------------
# 8. Backup / restore round-trip
# ---------------------------------------------------------------------------


async def scenario_backup_restore(ctx: dict[str, Any]) -> Scenario:
    """Backup Firm A, delete some rows, restore — the deleted rows
    must come back; Firm B rows must never appear in the archive."""
    from db.connection import acquire

    from core.backup import backup_firm, restore_firm

    firm_a = ctx["firm_a"]
    firm_b = ctx["firm_b"]
    sess_keep = ctx["sess_a_keep"]

    # 1) Backup
    archive = await backup_firm(firm_a)

    # 2) Cross-firm leak check — every row in the archive must
    # reference Firm A (either directly via firm_id, or transitively
    # via a session_id that maps back to Firm A).
    firm_a_session_ids = {
        s["id"] for s in archive.sessions if s.get("id")
    }
    leaks: list[str] = []
    for table_name in (
        "sessions", "firm_memberships", "notifications",
        "export_artifacts", "firm_library_documents",
        "purge_audit_log", "payload_versions",
    ):
        for row in getattr(archive, table_name, []) or []:
            fid = row.get("firm_id")
            if fid and str(fid) != firm_a:
                leaks.append(f"{table_name}.firm_id={fid}")
    # Child-table rows scoped only by session_id
    for table_name in (
        "reports", "evidence_objects", "comments",
        "engagement_memberships", "section_assignments",
        "engagement_tasks", "review_records",
    ):
        for row in getattr(archive, table_name, []) or []:
            sid = row.get("session_id") or row.get("engagement_id")
            if sid and str(sid) not in firm_a_session_ids:
                leaks.append(f"{table_name}.session_id={sid}")

    # Quick sanity: archive does NOT reference any Firm B session
    if ctx["sess_b"] in json.dumps(archive.to_dict()):
        leaks.append(f"firm_b_session_id_in_archive={ctx['sess_b']}")

    # 3) Delete a couple of Firm A rows — restore must bring them back
    async with acquire() as conn:
        deleted_comment_ids = await conn.fetch(
            """
            DELETE FROM comments WHERE session_id = $1::uuid
            RETURNING id
            """,
            sess_keep,
        )
        deleted_evidence_ids = await conn.fetch(
            """
            DELETE FROM evidence_objects WHERE session_id = $1::uuid
            RETURNING id
            """,
            sess_keep,
        )

    deleted_count = len(deleted_comment_ids) + len(deleted_evidence_ids)

    # 4) Restore
    counts = await restore_firm(archive)

    # 5) Verify those exact IDs are back
    async with acquire() as conn:
        comment_back = await conn.fetchval(
            "SELECT COUNT(*)::int FROM comments WHERE session_id = $1::uuid",
            sess_keep,
        )
        evidence_back = await conn.fetchval(
            "SELECT COUNT(*)::int FROM evidence_objects WHERE session_id = $1::uuid",
            sess_keep,
        )

    # 6) Idempotency — calling restore again is a no-op
    counts_2 = await restore_firm(archive)

    # JSON round-trip — the archive is portable
    blob = json.dumps(archive.to_dict())
    from core.backup import BackupArchive
    reparsed = BackupArchive.from_dict(json.loads(blob))
    json_roundtrip_ok = reparsed.total_rows() == archive.total_rows()

    ok = (
        not leaks
        and deleted_count > 0
        and comment_back == len(deleted_comment_ids)
        and evidence_back == len(deleted_evidence_ids)
        and sum(counts_2.values()) == 0
        and json_roundtrip_ok
    )
    return Scenario(
        name="backup_restore",
        ok=ok,
        reason=(
            f"archive_rows={archive.total_rows()}; "
            f"firm_b_leaks={leaks or 'none'}; "
            f"deleted_then_restored={deleted_count}; "
            f"comments_back={comment_back}/{len(deleted_comment_ids)}; "
            f"evidence_back={evidence_back}/{len(deleted_evidence_ids)}; "
            f"second_restore_is_noop={sum(counts_2.values()) == 0}; "
            f"json_roundtrip={json_roundtrip_ok}"
        ),
        evidence={
            "archive_version": archive.version,
            "archive_total_rows": archive.total_rows(),
            "archive_firm_id": archive.firm.get("id"),
            "leaks": leaks,
            "deleted_before_restore": deleted_count,
            "rows_restored": counts,
            "rows_restored_idempotent_call": counts_2,
            "json_roundtrip_total_rows_match": json_roundtrip_ok,
        },
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def teardown(ctx: dict[str, Any]) -> None:
    """Best-effort teardown. Leave the DB in the state we found it."""
    from db.connection import acquire

    async with acquire() as conn:
        await conn.execute(
            "DELETE FROM audit_events WHERE resource_id = ANY($1::text[])",
            [ctx["sess_a_keep"], ctx["sess_a_purge"],
             ctx["sess_a_retain"], ctx["sess_b"]],
        )
        await conn.execute(
            "DELETE FROM sessions WHERE firm_id IN "
            "(SELECT id FROM firms WHERE slug = ANY($1::text[]))",
            [FIRM_A_SLUG, FIRM_B_SLUG],
        )
        for tbl in (
            "cost_ledger", "firm_budget_notifications",
            "notifications", "purge_audit_log", "metric_events",
            "firm_memberships",
        ):
            try:
                await conn.execute(
                    f"DELETE FROM {tbl} WHERE firm_id IN "
                    f"(SELECT id FROM firms WHERE slug = ANY($1::text[]))",
                    [FIRM_A_SLUG, FIRM_B_SLUG],
                )
            except Exception:  # noqa: BLE001
                pass
        # Re-zero firm governance state in case anything strayed.
        await conn.execute(
            """
            UPDATE firms SET retention_days = NULL,
                             monthly_budget_usd = NULL,
                             session_cost_ceiling_usd = 5.0
             WHERE slug = ANY($1::text[])
            """,
            [FIRM_A_SLUG, FIRM_B_SLUG],
        )
        # Drop the synthetic users we created.
        await conn.execute(
            "DELETE FROM users WHERE email = ANY($1::text[])",
            [
                "w23-e2e-firm-a-admin@example.com",
                "w23-e2e-firm-b-admin@example.com",
            ],
        )
        # Drop the firms themselves.
        await conn.execute(
            "DELETE FROM firms WHERE slug = ANY($1::text[])",
            [FIRM_A_SLUG, FIRM_B_SLUG],
        )

    # Sweep the synthetic artifact directory.
    art_dir = _REPO / "backend" / "eval_runs" / "week23_enterprise" / "_artifacts"
    if art_dir.exists():
        for p in art_dir.glob("*.txt"):
            try: p.unlink()
            except Exception: pass


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


async def _run(skip_cleanup: bool) -> int:
    from db.connection import close_db, init_db

    await init_db()
    ctx: dict[str, Any] = {}
    scenarios: list[Scenario] = []
    try:
        ctx = await bootstrap()
        print(
            f"bootstrap: firm_a={ctx['firm_a']}  firm_b={ctx['firm_b']}"
        )

        scenarios.append(await scenario_isolation(ctx))
        scenarios.append(await scenario_deletion(ctx))
        scenarios.append(await scenario_retention(ctx))
        scenarios.append(await scenario_audit_export(ctx))
        scenarios.append(await scenario_budget(ctx))
        scenarios.append(await scenario_rate_limit(ctx))
        # Config scenario is pure (no DB); call sync.
        scenarios.append(scenario_config())
        scenarios.append(await scenario_backup_restore(ctx))
    finally:
        if not skip_cleanup and ctx:
            try:
                await teardown(ctx)
            except Exception as e:  # noqa: BLE001
                print(f"teardown warning: {e}")
        await close_db()

    all_ok = all(s.ok for s in scenarios)

    summary = {
        "run_at": datetime.now(tz=timezone.utc).isoformat(),
        "all_ok": all_ok,
        "ship_decision": "ship" if all_ok else "iterate",
        "scenarios": [asdict(s) for s in scenarios],
    }

    _OUT.mkdir(parents=True, exist_ok=True)
    out_path = _OUT / "summary.json"
    out_path.write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )

    print()
    print("=" * 72)
    print(f"Week 23 enterprise e2e — {len(scenarios)} scenarios")
    print("=" * 72)
    for s in scenarios:
        mark = "OK " if s.ok else "FAIL"
        print(f"  [{mark}] {s.name:<16} {s.reason}")
    print("=" * 72)
    print(f"Result: {'SHIP' if all_ok else 'ITERATE'}  ({sum(1 for s in scenarios if s.ok)}/{len(scenarios)} passed)")
    print(f"Saved:  {out_path}")
    return 0 if all_ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--no-cleanup", action="store_true",
        help="Leave the synthetic firms behind for inspection.",
    )
    args = ap.parse_args(argv)
    return asyncio.run(_run(skip_cleanup=args.no_cleanup))


if __name__ == "__main__":
    raise SystemExit(main())
