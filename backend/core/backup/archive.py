"""Firm backup + restore archive — Phase 5 / Week 23 / Day 4.

Portable JSON archive that round-trips a firm's data through
``backup_firm()`` → ``restore_firm()``.

Archive shape::

  {
    "version": 1,
    "exported_at": "<iso>",
    "firm": {"id": ..., "slug": ..., ...},
    "users": [...],
    "firm_memberships": [...],
    "sessions": [...],
    "reports": [...],
    "evidence_objects": [...],
    "comments": [...],
    "engagement_memberships": [...],
    "section_assignments": [...],
    "engagement_tasks": [...],
    "review_records": [...],
    "payload_versions": [...],
    "notifications": [...],
    "export_artifacts": [...],         # metadata only; file bytes
                                       # separate
    "firm_library_documents": [...],
    "purge_audit_log": [...],
  }

The full set of firm-scoped tables touched by Weeks 15-23 is
present. Restore re-inserts in topological order (parents
before children) so FK constraints hold; ``ON CONFLICT (id) DO
NOTHING`` makes the operation idempotent — restoring twice
doesn't double-insert.

Hard rules:
  - Tested round-trip — backup Firm A, restore into a fresh DB,
    verify identical state via row counts + checksum on a few
    high-trust fields.
  - Backup is firm-scoped — a backup of Firm A NEVER contains
    Firm B rows. Verified in test_tenant_isolation didn't catch
    this surface; W23/D4 test_backup_restore_round_trip does.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from db.connection import acquire

logger = logging.getLogger(__name__)


BACKUP_VERSION = 1


# ---------------------------------------------------------------------------
# Archive dataclass
# ---------------------------------------------------------------------------


@dataclass
class BackupArchive:
    """In-memory representation of the firm's backup. Round-trips
    through JSON via :meth:`to_dict` + :meth:`from_dict`."""

    version: int = BACKUP_VERSION
    exported_at: str = ""
    firm: dict[str, Any] = field(default_factory=dict)
    users: list[dict[str, Any]] = field(default_factory=list)
    firm_memberships: list[dict[str, Any]] = field(default_factory=list)
    sessions: list[dict[str, Any]] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    evidence_objects: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    engagement_memberships: list[dict[str, Any]] = field(default_factory=list)
    section_assignments: list[dict[str, Any]] = field(default_factory=list)
    engagement_tasks: list[dict[str, Any]] = field(default_factory=list)
    review_records: list[dict[str, Any]] = field(default_factory=list)
    payload_versions: list[dict[str, Any]] = field(default_factory=list)
    notifications: list[dict[str, Any]] = field(default_factory=list)
    export_artifacts: list[dict[str, Any]] = field(default_factory=list)
    firm_library_documents: list[dict[str, Any]] = field(default_factory=list)
    purge_audit_log: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BackupArchive":
        return cls(**{k: d.get(k, []) if k != "firm" and k != "version"
                                       and k != "exported_at" else d.get(k)
                      for k in cls.__dataclass_fields__})

    def total_rows(self) -> int:
        n = 0
        for k, f in self.__dataclass_fields__.items():
            v = getattr(self, k)
            if isinstance(v, list):
                n += len(v)
        return n


# ---------------------------------------------------------------------------
# Tables we walk + scoping SQL — kept in one place so a future
# table addition has a single edit point
# ---------------------------------------------------------------------------


_FIRM_SCOPED_TABLES = [
    # (archive_field, table_name, where_clause, columns)
    (
        "firm_memberships", "firm_memberships",
        "firm_id = $1::uuid",
        "id, firm_id, user_id, role, added_at",
    ),
    (
        "sessions", "sessions",
        "firm_id = $1::uuid",
        "id, firm_id, title, status, pipeline_state, "
        "report_mode, created_at, updated_at, "
        "created_by_user_id, metadata",
    ),
    (
        "reports", "reports",
        "session_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)",
        "id, session_id, summary, consulting_payload",
    ),
    (
        "evidence_objects", "evidence_objects",
        "session_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)",
        "id, session_id, claim, quote, source_type, source_url, "
        "source_title, source_score, created_at",
    ),
    (
        "comments", "comments",
        "session_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)",
        "id, session_id, author_id, body, anchor_type, anchor_ref, "
        "parent_comment_id, resolved_at, resolved_by, "
        "created_at, deleted_at",
    ),
    (
        "engagement_memberships", "engagement_memberships",
        "engagement_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)",
        "id, engagement_id, user_id, role, added_by, added_at, "
        "removed_at",
    ),
    (
        "section_assignments", "section_assignments",
        "session_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)",
        "id, session_id, section_path, assigned_to, assigned_by, "
        "status, updated_at",
    ),
    (
        "engagement_tasks", "engagement_tasks",
        "session_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)",
        "id, session_id, title, body, assigned_to, status, "
        "created_at, updated_at",
    ),
    (
        "review_records", "review_records",
        "session_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)",
        "id, session_id, action, actor_user_id, from_state, "
        "to_state, feedback, created_at",
    ),
    (
        "payload_versions", "payload_versions",
        "session_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)",
        "id, session_id, firm_id, version_number, payload_snapshot, "
        "change_type, change_summary, changed_section_paths, "
        "review_state_at_version, created_by, created_at",
    ),
    (
        "notifications", "notifications",
        "firm_id = $1::uuid",
        "id, recipient_id, firm_id, notification_type, session_id, "
        "source_ref, actor_id, summary, read, email_status, created_at",
    ),
    (
        "export_artifacts", "export_artifacts",
        "session_id IN (SELECT id FROM sessions WHERE firm_id = $1::uuid)",
        "id, session_id, firm_id, artifact_type, format, status, "
        "file_path, created_at",
    ),
    (
        "firm_library_documents", "firm_library_documents",
        "firm_id = $1::uuid",
        "id, firm_id, title, content_type, file_path, "
        "uploaded_at, retired_at",
    ),
    (
        "purge_audit_log", "purge_audit_log",
        "firm_id = $1::uuid",
        "id, session_id, firm_id, actor_user_id, purge_reason, "
        "rows_deleted, files_deleted, purged_at",
    ),
]


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def _to_jsonable(value: Any) -> Any:
    """Coerce DB values to JSON-safe scalars."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    # Fall back to str — never a runtime crash on an exotic type.
    return str(value)


async def backup_firm(firm_id: str | UUID) -> BackupArchive:
    """Export every firm-scoped row into a :class:`BackupArchive`.
    Reads at a single point in time; long-running pilots should
    snapshot during a quiet window."""
    fid = str(firm_id)
    archive = BackupArchive(
        exported_at=datetime.now(tz=timezone.utc).isoformat(),
    )

    async with acquire() as conn:
        firm_row = await conn.fetchrow(
            "SELECT id, slug, name, retention_days, monthly_budget_usd, "
            "session_cost_ceiling_usd FROM firms WHERE id = $1::uuid",
            fid,
        )
        if not firm_row:
            raise ValueError(f"firm {fid!r} does not exist")
        archive.firm = {
            k: _to_jsonable(firm_row[k])
            for k in firm_row.keys()
        }

        # users — only those who are members of THIS firm. A
        # cross-firm user would have rows in another firm's
        # membership; we still export their identity here so
        # the restore can re-link without depending on a
        # global users dump.
        user_rows = await conn.fetch(
            """
            SELECT u.id, u.email, u.full_name, u.role,
                   u.default_firm_id, u.created_at
              FROM users u
              JOIN firm_memberships m ON m.user_id = u.id
             WHERE m.firm_id = $1::uuid
            """,
            fid,
        )
        archive.users = [
            {k: _to_jsonable(r[k]) for k in r.keys()}
            for r in user_rows
        ]

        # Each firm-scoped table.
        for field_name, table, where, columns in _FIRM_SCOPED_TABLES:
            try:
                rows = await conn.fetch(
                    f"SELECT {columns} FROM {table} WHERE {where}",
                    fid,
                )
            except Exception as e:  # noqa: BLE001
                # Missing optional surface (e.g. migration not yet
                # applied) — record nothing, move on.
                logger.debug(
                    "backup: skipping %s (%s)", table, e,
                )
                continue
            data = [
                {k: _to_jsonable(r[k]) for k in r.keys()}
                for r in rows
            ]
            setattr(archive, field_name, data)

    return archive


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


# Topological order — parents first.
_RESTORE_ORDER = [
    ("firm", "firms",
     ["id", "slug", "name", "retention_days",
      "monthly_budget_usd", "session_cost_ceiling_usd"]),
    ("users", "users",
     ["id", "email", "full_name", "role", "default_firm_id",
      "created_at"]),
    ("firm_memberships", "firm_memberships",
     ["id", "firm_id", "user_id", "role", "added_at"]),
    ("sessions", "sessions",
     ["id", "firm_id", "title", "status", "pipeline_state",
      "report_mode", "created_at", "updated_at",
      "created_by_user_id", "metadata"]),
    ("reports", "reports",
     ["id", "session_id", "summary", "consulting_payload"]),
    ("evidence_objects", "evidence_objects",
     ["id", "session_id", "claim", "quote", "source_type",
      "source_url", "source_title", "source_score", "created_at"]),
    ("comments", "comments",
     ["id", "session_id", "author_id", "body", "anchor_type",
      "anchor_ref", "parent_comment_id", "resolved_at",
      "resolved_by", "created_at", "deleted_at"]),
    ("engagement_memberships", "engagement_memberships",
     ["id", "engagement_id", "user_id", "role", "added_by",
      "added_at", "removed_at"]),
    ("section_assignments", "section_assignments",
     ["id", "session_id", "section_path", "assigned_to",
      "assigned_by", "status", "updated_at"]),
    ("engagement_tasks", "engagement_tasks",
     ["id", "session_id", "title", "body", "assigned_to",
      "status", "created_at", "updated_at"]),
    ("review_records", "review_records",
     ["id", "session_id", "action", "actor_user_id",
      "from_state", "to_state", "feedback", "created_at"]),
    ("payload_versions", "payload_versions",
     ["id", "session_id", "firm_id", "version_number",
      "payload_snapshot", "change_type", "change_summary",
      "changed_section_paths", "review_state_at_version",
      "created_by", "created_at"]),
    ("notifications", "notifications",
     ["id", "recipient_id", "firm_id", "notification_type",
      "session_id", "source_ref", "actor_id", "summary", "read",
      "email_status", "created_at"]),
    ("export_artifacts", "export_artifacts",
     ["id", "session_id", "firm_id", "artifact_type", "format",
      "status", "file_path", "created_at"]),
    ("firm_library_documents", "firm_library_documents",
     ["id", "firm_id", "title", "content_type", "file_path",
      "uploaded_at", "retired_at"]),
    ("purge_audit_log", "purge_audit_log",
     ["id", "session_id", "firm_id", "actor_user_id",
      "purge_reason", "rows_deleted", "files_deleted",
      "purged_at"]),
]


async def restore_firm(archive: BackupArchive) -> dict[str, int]:
    """Re-insert the archive's rows into the current DB. Returns
    counts-per-table. Idempotent via ``ON CONFLICT (id) DO
    NOTHING`` — restoring twice doesn't duplicate."""
    counts: dict[str, int] = {}
    async with acquire() as conn:
        for archive_field, table, cols in _RESTORE_ORDER:
            rows = (
                [archive.firm] if archive_field == "firm"
                else getattr(archive, archive_field) or []
            )
            inserted = 0
            for row in rows:
                if not row:
                    continue
                placeholders = ", ".join(
                    f"${i+1}" for i in range(len(cols))
                )
                col_list = ", ".join(cols)
                values: list[Any] = []
                for c in cols:
                    v = row.get(c)
                    # asyncpg needs JSON columns serialised when
                    # the value is a dict/list.
                    if isinstance(v, (dict, list)):
                        v = json.dumps(v)
                    values.append(v)
                sql = (
                    f"INSERT INTO {table} ({col_list}) "
                    f"VALUES ({placeholders}) "
                    f"ON CONFLICT (id) DO NOTHING"
                )
                try:
                    result = await conn.execute(sql, *values)
                    if "INSERT 0 1" in result:
                        inserted += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "restore: insert into %s failed: %s",
                        table, e,
                    )
            counts[table] = inserted
    return counts


__all__ = [
    "BACKUP_VERSION",
    "BackupArchive",
    "backup_firm",
    "restore_firm",
]
