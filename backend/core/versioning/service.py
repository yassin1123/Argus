"""Payload version history service — Phase 4 / Week 19 / Day 1.

CRUD around the W19/D1 ``payload_versions`` table. Five entry points:

  - :func:`create_version` — append a new version with diff +
    review-state capture. version_number = prior max + 1.
  - :func:`list_versions` — metadata-only feed for the history
    reader (NO full payloads per W19/D1 hard rule).
  - :func:`get_version` — full snapshot for one specific version.
  - :func:`get_current_version` — convenience wrapper for the
    head version (max version_number).
  - :func:`ensure_initial_version` — idempotent helper for the
    save_report write path: creates v1 from the live reports row
    when no version row exists for the session. New engagements
    get a v1 the first time the writer pipeline persists; existing
    engagements got v1 from migration 044's backfill.

Per W19/D1 hard rules:

  - Append-only. Nothing in this module overwrites a prior
    version. ``RESTORE`` is W19/D2's job and creates a NEW
    version equal to the prior snapshot, not an in-place mutation.
  - list_versions returns metadata only — no payload_snapshot
    bytes — so the history reader stays fast.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from db.connection import acquire

from .diff import changed_sections
from .types import ChangeType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class PayloadVersionSummary:
    """Metadata-only row shape — used by :func:`list_versions`.
    Never carries ``payload_snapshot`` bytes."""

    id: str
    session_id: str
    firm_id: str
    version_number: int
    change_type: str
    change_summary: str | None
    changed_section_paths: list[str]
    review_state_at_version: str | None
    created_by: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> "PayloadVersionSummary":
        csp = row.get("changed_section_paths") if isinstance(row, dict) else row["changed_section_paths"]
        if isinstance(csp, str):
            try:
                csp = json.loads(csp)
            except Exception:
                csp = []
        return cls(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            firm_id=str(row["firm_id"]),
            version_number=int(row["version_number"]),
            change_type=str(row["change_type"]),
            change_summary=row.get("change_summary") if isinstance(row, dict) else row["change_summary"],
            changed_section_paths=list(csp or []),
            review_state_at_version=row.get("review_state_at_version")
                if isinstance(row, dict) else row["review_state_at_version"],
            created_by=str(row["created_by"]) if row.get("created_by") else None,
            created_at=row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat")
                        else str(row["created_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "firm_id": self.firm_id,
            "version_number": self.version_number,
            "change_type": self.change_type,
            "change_summary": self.change_summary,
            "changed_section_paths": self.changed_section_paths,
            "review_state_at_version": self.review_state_at_version,
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass
class PayloadVersion(PayloadVersionSummary):
    """Full version row including the snapshot bytes. Used by
    :func:`get_version` / :func:`get_current_version`."""

    payload_snapshot: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Any) -> "PayloadVersion":  # type: ignore[override]
        summary = PayloadVersionSummary.from_row(row)
        snap = row["payload_snapshot"]
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except Exception:
                snap = {}
        return cls(
            id=summary.id,
            session_id=summary.session_id,
            firm_id=summary.firm_id,
            version_number=summary.version_number,
            change_type=summary.change_type,
            change_summary=summary.change_summary,
            changed_section_paths=summary.changed_section_paths,
            review_state_at_version=summary.review_state_at_version,
            created_by=summary.created_by,
            created_at=summary.created_at,
            payload_snapshot=snap or {},
        )

    def to_dict(self) -> dict[str, Any]:  # type: ignore[override]
        d = super().to_dict()
        d["payload_snapshot"] = self.payload_snapshot
        return d


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------


async def _firm_id_for_session(session_id: UUID) -> UUID | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id = $1::uuid", session_id,
        )
    return row["firm_id"] if row else None


async def _review_state_for_session(session_id: UUID) -> str | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT review_state FROM sessions WHERE id = $1::uuid", session_id,
        )
    return str(row["review_state"]) if row and row["review_state"] else None


async def _next_version_number(session_id: UUID) -> int:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT COALESCE(MAX(version_number), 0) + 1 AS n
              FROM payload_versions
             WHERE session_id = $1::uuid
            """,
            session_id,
        )
    return int(row["n"] or 1)


async def _prior_version_snapshot(
    session_id: UUID,
) -> dict[str, Any] | None:
    """Pull the most-recent version's payload_snapshot for the
    diff against the incoming payload. Returns ``None`` when no
    prior version exists (the new version IS v1)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT payload_snapshot
              FROM payload_versions
             WHERE session_id = $1::uuid
             ORDER BY version_number DESC
             LIMIT 1
            """,
            session_id,
        )
    if not row:
        return None
    snap = row["payload_snapshot"]
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except Exception:
            snap = {}
    return snap or {}


async def _load_live_payload_for_session(session_id: UUID) -> dict[str, Any]:
    """Build the same flattened "what every service sees" payload
    shape used by W16 + W17. Falls back to an empty dict when no
    reports row exists (a brand-new session pre-pipeline)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT recommendation, confidence_level, summary, key_reasons, risks,
                   counterarguments, next_steps, sources, caveats, consulting_payload
              FROM reports WHERE session_id = $1::uuid
            """,
            session_id,
        )
    if not row:
        return {}
    out: dict[str, Any] = {}
    cp = row["consulting_payload"]
    if isinstance(cp, str):
        try:
            cp = json.loads(cp)
        except Exception:
            cp = {}
    if isinstance(cp, dict):
        out.update(cp)
    for k in ("recommendation", "confidence_level", "summary", "key_reasons",
              "risks", "counterarguments", "next_steps", "sources", "caveats"):
        v = row[k]
        if isinstance(v, str) and k in (
            "key_reasons", "risks", "counterarguments", "next_steps", "sources",
        ):
            try:
                v = json.loads(v)
            except Exception:
                pass
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_version(
    session_id: UUID,
    payload: dict[str, Any],
    change_type: ChangeType | str,
    *,
    created_by: UUID | None = None,
    change_summary: str | None = None,
) -> PayloadVersion:
    """Append a new payload version. Computes ``version_number``
    (prior max + 1), diffs against the prior version to populate
    ``changed_section_paths``, captures the current
    ``sessions.review_state``, persists the snapshot. Never
    overwrites a prior version (W19/D1 hard rule: append-only)."""
    if isinstance(change_type, str):
        change_type_enum = ChangeType(change_type)
    else:
        change_type_enum = change_type

    firm_id = await _firm_id_for_session(session_id)
    if firm_id is None:
        raise ValueError(f"session not found: {session_id}")

    prior = await _prior_version_snapshot(session_id)
    diff_paths = changed_sections(prior, payload) if prior is not None else []
    version_number = await _next_version_number(session_id)
    review_state = await _review_state_for_session(session_id)

    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO payload_versions
                (session_id, firm_id, version_number, payload_snapshot,
                 change_type, change_summary, changed_section_paths,
                 review_state_at_version, created_by)
            VALUES ($1::uuid, $2::uuid, $3, $4::jsonb,
                    $5, $6, $7::jsonb, $8, $9::uuid)
            RETURNING id, session_id, firm_id, version_number,
                      payload_snapshot, change_type, change_summary,
                      changed_section_paths, review_state_at_version,
                      created_by, created_at
            """,
            session_id, firm_id, version_number,
            json.dumps(payload or {}),
            change_type_enum.value,
            change_summary,
            json.dumps(diff_paths),
            review_state,
            created_by,
        )
    return PayloadVersion.from_row(row)


async def ensure_initial_version(
    session_id: UUID,
    *,
    created_by: UUID | None = None,
) -> PayloadVersion | None:
    """Idempotent — if no version row exists for the session,
    create v1 with change_type=INITIAL from the live reports row.
    No-op (returns None) when:

      - a prior version already exists (the common case after the
        W19/D1 backfill), OR
      - no reports row exists for the session yet (a brand-new
        session that hasn't run the writer pipeline).

    Called by save_report after every upsert as a defensive hook
    so new engagements naturally get a v1 baseline.
    """
    async with acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT 1 FROM payload_versions WHERE session_id = $1::uuid LIMIT 1",
            session_id,
        )
    if existing:
        return None

    payload = await _load_live_payload_for_session(session_id)
    if not payload:
        return None

    return await create_version(
        session_id, payload, ChangeType.INITIAL,
        created_by=created_by,
        change_summary="Initial generation",
    )


async def list_versions(session_id: UUID) -> list[PayloadVersionSummary]:
    """Metadata-only feed, newest first. Per W19/D1 hard rule, this
    NEVER returns the full payload_snapshot bytes — the history
    reader pulls a specific version on demand via
    :func:`get_version`."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, firm_id, version_number,
                   change_type, change_summary, changed_section_paths,
                   review_state_at_version, created_by, created_at
              FROM payload_versions
             WHERE session_id = $1::uuid
             ORDER BY version_number DESC
            """,
            session_id,
        )
    return [PayloadVersionSummary.from_row(r) for r in rows]


async def get_version(
    session_id: UUID, version_number: int,
) -> PayloadVersion | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, firm_id, version_number,
                   payload_snapshot, change_type, change_summary,
                   changed_section_paths, review_state_at_version,
                   created_by, created_at
              FROM payload_versions
             WHERE session_id = $1::uuid AND version_number = $2
            """,
            session_id, int(version_number),
        )
    return PayloadVersion.from_row(row) if row else None


async def get_current_version(session_id: UUID) -> PayloadVersion | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, firm_id, version_number,
                   payload_snapshot, change_type, change_summary,
                   changed_section_paths, review_state_at_version,
                   created_by, created_at
              FROM payload_versions
             WHERE session_id = $1::uuid
             ORDER BY version_number DESC
             LIMIT 1
            """,
            session_id,
        )
    return PayloadVersion.from_row(row) if row else None


__all__ = [
    "PayloadVersion",
    "PayloadVersionSummary",
    "create_version",
    "ensure_initial_version",
    "get_current_version",
    "get_version",
    "list_versions",
]
