"""Version restore — Phase 4 / Week 19 / Day 2.

Restoring a prior version is an **append**: it materialises the
target snapshot as a NEW current version (change_type=RESTORE).
History is preserved untouched per the W19/D1 hard rule
"don't destroy versions on restore".

Side-effects (consistent with W15's "editing costs the approval"
posture):

  1. Permission gate — engagement lead, the original author of
     the engagement, or firm admin only. Contributors cannot
     restore the whole engagement.
  2. In-flight deepening check — refuse if a section_deepening
     is currently queued/running. Restoring would race the
     deepening's pending merge.
  3. Approved-engagement gate — when ``review_state ∈
     {approved, delivered}``, the caller MUST pass
     ``confirm_revert=True`` (the API layer converts the missing
     confirmation to a 409 with a clean reason). When the flag
     is set we call :func:`auto_revert_if_locked` first so the
     engagement comes off approved before the snapshot lands.
  4. Persist the snapshot back onto the reports row (base
     columns + consulting_payload split).
  5. Append a new RESTORE version row.
  6. Flag every ``ready`` artifact stale (W15 pattern).
  7. Audit + dispatch ``VERSION_RESTORED`` notification.

Best-effort on the notify + audit; never roll back the restore.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from db.connection import acquire

from .service import (
    PayloadVersion,
    _firm_id_for_session,
    create_version,
    get_version,
)
from .types import ChangeType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class RestoreResult:
    ok: bool
    new_version: PayloadVersion | None = None
    restored_version_number: int | None = None
    reverted_from_approved: bool = False
    artifacts_marked_stale: int = 0
    status_code: int = 200
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "new_version": self.new_version.to_dict() if self.new_version else None,
            "restored_version_number": self.restored_version_number,
            "reverted_from_approved": self.reverted_from_approved,
            "artifacts_marked_stale": self.artifacts_marked_stale,
            "status_code": self.status_code,
            "reason": self.reason,
            "extra": self.extra,
        }


# Canonical error reason strings — short + 4xx-body-safe.
_NOT_FOUND = "session or version not found"
_PERM_DENIED = "engagement lead, the original author, or firm admin only"
_IN_FLIGHT_DEEPEN = "a section deepening is currently running; wait for it to finish"
_NEEDS_CONFIRM = (
    "restore on an approved/delivered engagement requires confirm_revert=true "
    "— restoring will revert the approval"
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


_BASE_COLUMNS = (
    "recommendation", "confidence_level", "summary",
    "key_reasons", "risks", "counterarguments", "next_steps",
    "sources", "caveats",
)


async def _load_session_meta(session_id: UUID) -> dict[str, Any] | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT firm_id, created_by_user_id, review_state
              FROM sessions WHERE id = $1::uuid
            """,
            session_id,
        )
    return dict(row) if row else None


async def _active_lead_id(session_id: UUID) -> UUID | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id FROM engagement_memberships
             WHERE engagement_id = $1::uuid
               AND role = 'lead'
               AND removed_at IS NULL
             LIMIT 1
            """,
            session_id,
        )
    return row["user_id"] if row else None


async def _is_firm_admin(firm_id: UUID, user_id: UUID) -> bool:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT role FROM firm_memberships
             WHERE firm_id = $1::uuid AND user_id = $2::uuid
            """,
            firm_id, user_id,
        )
    return bool(row) and str(row["role"]).lower() == "admin"


async def _has_in_flight_deepening(session_id: UUID) -> bool:
    """W19/D2 surface check — block restore when a section
    deepening is queued/running so we don't race its pending
    merge."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM section_deepening_runs
             WHERE session_id = $1::uuid
               AND status IN ('queued', 'running')
             LIMIT 1
            """,
            session_id,
        )
    return row is not None


async def _persist_snapshot_to_reports(
    session_id: UUID, snapshot: dict[str, Any],
) -> None:
    """Split the flattened snapshot back into base reports columns
    + consulting_payload and UPDATE the reports row in place. The
    snapshot is the "what every service sees as payload" shape:
    base fields at the top + consulting_payload subkeys flattened.
    We rebuild the inverse here so the reports row matches the
    snapshot after the call."""
    base: dict[str, Any] = {}
    cp: dict[str, Any] = {}
    for k, v in (snapshot or {}).items():
        if k in _BASE_COLUMNS:
            base[k] = v
        else:
            cp[k] = v

    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE reports SET
                recommendation    = $2,
                confidence_level  = $3,
                summary           = $4,
                key_reasons       = $5::jsonb,
                risks             = $6::jsonb,
                counterarguments  = $7::jsonb,
                next_steps        = $8::jsonb,
                sources           = $9::jsonb,
                caveats           = $10,
                consulting_payload = $11::jsonb
             WHERE session_id = $1::uuid
            """,
            session_id,
            base.get("recommendation"),
            base.get("confidence_level"),
            base.get("summary"),
            json.dumps(base.get("key_reasons") or []),
            json.dumps(base.get("risks") or []),
            json.dumps(base.get("counterarguments") or []),
            json.dumps(base.get("next_steps") or []),
            json.dumps(base.get("sources") or []),
            base.get("caveats") or "",
            json.dumps(cp),
        )


async def _flag_artifacts_stale(session_id: UUID, reason: str) -> int:
    """Mirrors :func:`core.review.service._mark_artifacts_stale` —
    tag every ``ready`` artifact with ``metadata.stale_since_revert
    = true``. Returns the row count flipped."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE export_artifacts
               SET metadata = COALESCE(metadata, '{}'::jsonb)
                              || jsonb_build_object(
                                    'stale_since_revert', TRUE,
                                    'stale_reason', $2::text)
             WHERE session_id = $1::uuid AND status = 'ready'
            RETURNING id
            """,
            session_id, reason,
        )
    return len(rows)


async def _audit_restore(
    session_id: UUID,
    actor_id: UUID,
    target_version: int,
    new_version: int,
    reverted: bool,
) -> None:
    """Best-effort audit row for the restore action."""
    try:
        from audit.queries import append_event
        await append_event(
            action="version.restored",
            actor_user_id=str(actor_id),
            resource_type="session",
            resource_id=str(session_id),
            payload={
                "session_id": str(session_id),
                "restored_version_number": target_version,
                "new_version_number": new_version,
                "reverted_from_approved": reverted,
            },
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("restore: audit append failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_LOCKED_STATES = {"approved", "delivered"}


async def restore_version(
    session_id: UUID,
    target_version_number: int,
    actor_id: UUID,
    *,
    confirm_revert: bool = False,
) -> RestoreResult:
    """Restore a prior version. See module docstring for the full
    seven-step contract."""
    sess_meta = await _load_session_meta(session_id)
    if sess_meta is None:
        return RestoreResult(ok=False, status_code=404, reason=_NOT_FOUND)
    firm_id = UUID(str(sess_meta["firm_id"]))
    review_state = str(sess_meta["review_state"] or "draft")
    created_by = sess_meta.get("created_by_user_id")

    target = await get_version(session_id, int(target_version_number))
    if target is None:
        return RestoreResult(ok=False, status_code=404, reason=_NOT_FOUND)

    # 1. Permission gate.
    is_admin = await _is_firm_admin(firm_id, actor_id)
    lead_id = await _active_lead_id(session_id)
    is_lead = bool(lead_id) and str(lead_id) == str(actor_id)
    is_author = created_by is not None and str(created_by) == str(actor_id)
    if not (is_admin or is_lead or is_author):
        return RestoreResult(ok=False, status_code=403, reason=_PERM_DENIED)

    # 2. In-flight deepening guard.
    if await _has_in_flight_deepening(session_id):
        return RestoreResult(ok=False, status_code=409, reason=_IN_FLIGHT_DEEPEN)

    # 3. Approved-state confirmation guard.
    if review_state in _LOCKED_STATES and not confirm_revert:
        return RestoreResult(
            ok=False, status_code=409, reason=_NEEDS_CONFIRM,
            extra={"requires_confirm_revert": True, "review_state": review_state},
        )

    reverted_from_approved = False
    if review_state in _LOCKED_STATES and confirm_revert:
        try:
            from core.review.service import auto_revert_if_locked
            revert = await auto_revert_if_locked(
                session_id, actor_id,
                f"restore to version {target_version_number}",
            )
            reverted_from_approved = revert is not None and bool(revert.ok)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "restore: auto_revert_if_locked failed (non-fatal): %s", exc,
            )

    # 4. Persist the snapshot back onto reports.
    await _persist_snapshot_to_reports(session_id, target.payload_snapshot)

    # 5. Append a RESTORE version (history append-only).
    new_version = await create_version(
        session_id,
        dict(target.payload_snapshot or {}),
        ChangeType.RESTORE,
        created_by=actor_id,
        change_summary=f"Restored from version {target_version_number}",
    )

    # 6. Flag artifacts stale (W15 pattern).
    n_stale = await _flag_artifacts_stale(
        session_id,
        f"version restore: snapshot v{target_version_number} -> v{new_version.version_number}",
    )

    # 7a. Audit.
    await _audit_restore(
        session_id, actor_id,
        target_version_number, new_version.version_number,
        reverted_from_approved,
    )

    # 7b. Notify the lead (W18 wiring; best-effort).
    try:
        from core.notifications.wiring import notify_version_restored
        await notify_version_restored(
            session_id=session_id, firm_id=firm_id, actor_id=actor_id,
            restored_version_number=int(target_version_number),
            new_version_number=int(new_version.version_number),
            reverted_from_approved=reverted_from_approved,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("restore: notification dispatch failed: %s", exc)

    return RestoreResult(
        ok=True,
        new_version=new_version,
        restored_version_number=int(target_version_number),
        reverted_from_approved=reverted_from_approved,
        artifacts_marked_stale=n_stale,
    )


__all__ = ["RestoreResult", "restore_version"]
