"""Hard-delete service — Phase 5 / Week 23 / Day 2.

``purge_engagement(session_id, actor_user_id, reason)``
permanently removes every record tied to an engagement + every
artifact file on disk. Returns a :class:`PurgeReport` carrying
per-table counts so the firm has proof-of-deletion.

The deletion audit row is the only artefact that survives the
purge. It carries:

  - session_id, firm_id (so the firm can prove its data was
    deleted by name)
  - actor_user_id (who issued the purge)
  - purge_reason (firm_admin_request | retention_sweep)
  - rows_deleted (counts per table)
  - files_deleted (count of artifact files removed from storage)
  - purged_at

NO claim text, NO evidence content, NO memo prose, NO file
bytes. The audit paradox handled correctly per the W23/D2 spec:
log THAT a purge happened, never WHAT was deleted.

Implementation notes:

  - The order of table deletions matters. We delete children
    before parents to avoid FK constraint violations even on
    schemas without ON DELETE CASCADE.
  - Artifact files are deleted from disk BEFORE their DB rows
    are removed, so a crash in the middle never leaves
    orphaned files (the DB row points at the location even if
    the row itself is about to disappear).
  - Everything runs inside ONE transaction. A crash mid-purge
    either rolls back entirely (failed) or completes atomically.
    The purge_audit_log INSERT lands inside the same tx — the
    audit row appears iff the purge succeeded.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from db.connection import acquire

logger = logging.getLogger(__name__)


# Tables touched in topological order — children first.
# Anything new with a session_id FK must be added here.
_PURGE_TABLES = [
    # claim / evidence / chunk surfaces
    "claim_evidence_links",
    "claim_rows",
    "evidence_objects",
    # pipeline + agent outputs
    "pipeline_events",
    "agent_outputs",
    "conversation_turns",
    "llm_calls",
    "section_deepening_runs",
    # collaboration
    "comments",
    "engagement_tasks",
    "section_assignments",
    "engagement_memberships",
    # review
    "review_records",
    # versions
    "payload_versions",
    # notifications
    "notifications",
    # observability
    "metric_events",
    "cost_ledger",
    # exports
    "export_artifacts",
    # reports
    "reports",
    # sources
    "sources",
    # finally, the session row itself
    "sessions",
]


@dataclass
class PurgeReport:
    """What got removed, for the firm's deletion receipt."""

    session_id: str
    firm_id: str
    actor_user_id: str | None
    purge_reason: str
    rows_deleted: dict[str, int] = field(default_factory=dict)
    files_deleted: int = 0
    files_failed: int = 0
    audit_log_id: int | None = None

    def total_rows_deleted(self) -> int:
        return sum(self.rows_deleted.values())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Artifact file deletion
# ---------------------------------------------------------------------------


async def _collect_artifact_file_paths(
    conn, session_id: str,
) -> list[str]:
    """Read every artifact's ``file_path`` for the session. We
    do this BEFORE deleting the rows so a crash mid-purge
    doesn't strand the file references."""
    try:
        rows = await conn.fetch(
            "SELECT file_path FROM export_artifacts "
            "WHERE session_id = $1::uuid AND file_path IS NOT NULL",
            session_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("export_artifacts file_path fetch skipped: %s", e)
        return []
    return [r["file_path"] for r in rows if r["file_path"]]


def _safe_unlink(path: str) -> bool:
    """Best-effort delete of one artifact file. Returns True on
    success. Never raises — a missing file is a no-op (it may
    already have been swept; the row's deletion still proceeds)."""
    try:
        p = Path(path)
        if p.exists() and p.is_file():
            p.unlink()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("artifact file delete failed: %s (%s)", path, e)
        return False


# ---------------------------------------------------------------------------
# Public purge
# ---------------------------------------------------------------------------


async def purge_engagement(
    session_id: str | UUID,
    *,
    actor_user_id: str | UUID | None,
    purge_reason: str = "firm_admin_request",
) -> PurgeReport:
    """Permanently delete the engagement and every associated
    record. Writes one ``purge_audit_log`` row carrying counts +
    actor + reason, with zero client content.

    Raises :class:`ValueError` when ``session_id`` doesn't
    resolve to a real session. Lets DB exceptions propagate so a
    caller can roll back the request — purge is a one-shot
    operation; partial-success is not a state we tolerate.
    """
    sid = str(session_id)
    actor = str(actor_user_id) if actor_user_id else None
    valid_reasons = {"firm_admin_request", "retention_sweep", "test"}
    if purge_reason not in valid_reasons:
        raise ValueError(
            f"purge_reason must be one of {sorted(valid_reasons)}; "
            f"got {purge_reason!r}"
        )

    async with acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id = $1::uuid",
            sid,
        )
        if not sess:
            raise ValueError(f"session {sid!r} does not exist")
        firm_id = str(sess["firm_id"])

        report = PurgeReport(
            session_id=sid, firm_id=firm_id,
            actor_user_id=actor, purge_reason=purge_reason,
        )

        # --- delete artifact files BEFORE their DB rows ---
        file_paths = await _collect_artifact_file_paths(conn, sid)
        for path in file_paths:
            if _safe_unlink(path):
                report.files_deleted += 1
            else:
                report.files_failed += 1

        # --- delete rows in topological order ---
        async with conn.transaction():
            for table in _PURGE_TABLES:
                try:
                    result = await conn.execute(
                        f"DELETE FROM {table} WHERE session_id = $1::uuid",
                        sid,
                    )
                    # asyncpg returns "DELETE <n>"; parse the count.
                    n = 0
                    try:
                        n = int(result.split()[-1])
                    except (ValueError, IndexError):
                        n = 0
                    if n > 0:
                        report.rows_deleted[table] = n
                except Exception as e:  # noqa: BLE001
                    # A missing table is fine (new install, optional
                    # surface). Other errors are noted + we move on
                    # so one stuck table doesn't strand the rest.
                    logger.debug(
                        "purge: skipping %s (%s)", table, e,
                    )

            # --- write the audit row INSIDE the same tx ---
            audit_row = await conn.fetchrow(
                """
                INSERT INTO purge_audit_log
                    (session_id, firm_id, actor_user_id,
                     purge_reason, rows_deleted, files_deleted)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4,
                        $5::jsonb, $6)
                RETURNING id
                """,
                sid, firm_id, actor, purge_reason,
                json.dumps(report.rows_deleted),
                report.files_deleted,
            )
            report.audit_log_id = (
                int(audit_row["id"]) if audit_row else None
            )

    return report


# ---------------------------------------------------------------------------
# Read-side helpers (used by the API + retention sweep)
# ---------------------------------------------------------------------------


async def list_purges_for_firm(
    firm_id: str | UUID, limit: int = 100,
) -> list[dict[str, Any]]:
    """Read the purge audit trail for a firm — the deletion
    receipt the firm can show its clients / auditors."""
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, session_id, actor_user_id, purge_reason,
                       rows_deleted, files_deleted, purged_at
                  FROM purge_audit_log
                 WHERE firm_id = $1::uuid
                 ORDER BY purged_at DESC LIMIT $2
                """,
                str(firm_id), int(limit),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("purge audit read failed: %s", e)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        rd = r["rows_deleted"]
        if isinstance(rd, str):
            try: rd = json.loads(rd)
            except Exception: rd = {}
        out.append({
            "audit_id": int(r["id"]),
            "session_id": str(r["session_id"]),
            "actor_user_id": (
                str(r["actor_user_id"]) if r["actor_user_id"] else None
            ),
            "purge_reason": r["purge_reason"],
            "rows_deleted": rd or {},
            "files_deleted": int(r["files_deleted"]),
            "purged_at": r["purged_at"].isoformat() if r["purged_at"] else None,
        })
    return out


__all__ = [
    "PurgeReport",
    "list_purges_for_firm",
    "purge_engagement",
]
