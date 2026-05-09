"""Phase 2 / Week 6 / Day 2 — service layer for firm-mode CRUD.

Encapsulates the DB writes, audit-log entries, and resolver-cache
invalidation for ``firm_modes``. The HTTP layer in
``backend/api/firm_modes.py`` is a thin shell over these functions.

Mode-name regex is the slug format ``^[a-z][a-z0-9_]{2,40}$`` — keeps
prompt templates safe (no whitespace/special chars) and prevents the
admin UI from accepting display strings like ``"My Mode!"`` as
identifiers.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from db.connection import acquire

from .resolver import (
    _validate_overlay_payload,
    invalidate_firm_mode,
    is_known_built_in,
)
from .types import ModeConfigError, ModeNotFoundError

logger = logging.getLogger(__name__)

MODE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


@dataclass
class FirmMode:
    """Wire-shape of a firm_modes row."""

    id: str
    firm_id: str
    name: str
    base_mode: str | None
    config: dict[str, Any]
    created_by: str | None
    created_at: str
    updated_at: str
    retired_at: str | None

    @classmethod
    def from_row(cls, row: Any) -> "FirmMode":
        cfg = row["config"]
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        return cls(
            id=str(row["id"]),
            firm_id=str(row["firm_id"]),
            name=row["name"],
            base_mode=row["base_mode"],
            config=cfg if isinstance(cfg, dict) else {},
            created_by=str(row["created_by"]) if row["created_by"] else None,
            created_at=row["created_at"].isoformat() if row["created_at"] else "",
            updated_at=row["updated_at"].isoformat() if row["updated_at"] else "",
            retired_at=row["retired_at"].isoformat() if row["retired_at"] else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "firm_id": self.firm_id,
            "name": self.name,
            "base_mode": self.base_mode,
            "config": self.config,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "retired_at": self.retired_at,
        }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_mode_name(name: str) -> None:
    if not isinstance(name, str) or not MODE_NAME_RE.match(name):
        raise ModeConfigError(
            f"mode name {name!r} must match {MODE_NAME_RE.pattern} "
            "(lowercase, digits, underscores; 3-41 chars)"
        )


def _validate_base_mode(base_mode: str | None) -> None:
    if base_mode is None or base_mode == "":
        return
    if not is_known_built_in(base_mode):
        raise ModeConfigError(
            f"base_mode {base_mode!r} is not a known built-in mode"
        )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


async def _audit(
    *,
    actor_user_id: str | None,
    actor_email: str | None,
    action: str,
    firm_id: str,
    mode_name: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort domain-level audit. Never raises — the caller's mutation
    has already happened by the time we're here."""
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_events (
                    actor_user_id, actor_email, action, resource_type,
                    resource_id, payload
                ) VALUES (
                    $1::uuid, $2, $3, 'firm_mode', $4, $5::jsonb
                )
                """,
                actor_user_id,
                actor_email,
                action,
                f"{firm_id}:{mode_name}",
                json.dumps({"firm_id": firm_id, "mode_name": mode_name, **payload}),
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("audit %s skipped: %s", action, e)


def _config_diff(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, Any]:
    """Return only the keys whose value changed. Full configs would
    bloat the audit row — and the keys-that-changed view is what an
    auditor reads anyway."""
    out: dict[str, Any] = {}
    for key in set(before) | set(after):
        if before.get(key) != after.get(key):
            out[key] = {"before": before.get(key), "after": after.get(key)}
    return out


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_firm_mode(
    *,
    firm_id: str,
    name: str,
    base_mode: str | None,
    config: dict[str, Any],
    created_by: str | None,
    actor_email: str | None = None,
) -> FirmMode:
    _validate_mode_name(name)
    _validate_base_mode(base_mode)
    _validate_overlay_payload(config)

    async with acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM firm_modes WHERE firm_id = $1::uuid AND name = $2",
            firm_id,
            name,
        )
        if existing:
            raise ModeConfigError(
                f"firm already has a mode named {name!r}; "
                "PATCH the existing row instead"
            )
        row = await conn.fetchrow(
            """
            INSERT INTO firm_modes (firm_id, name, base_mode, config, created_by)
            VALUES ($1::uuid, $2, $3, $4::jsonb, $5::uuid)
            RETURNING *
            """,
            firm_id,
            name,
            base_mode,
            json.dumps(config),
            created_by,
        )

    await _audit(
        actor_user_id=created_by,
        actor_email=actor_email,
        action="firm_modes.create",
        firm_id=firm_id,
        mode_name=name,
        payload={
            "base_mode": base_mode,
            "config_keys": sorted(config.keys()),
        },
    )
    invalidate_firm_mode(name, firm_id)
    return FirmMode.from_row(row)


async def list_firm_modes(
    firm_id: str, *, include_retired: bool = False
) -> list[FirmMode]:
    sql = """
        SELECT * FROM firm_modes
        WHERE firm_id = $1::uuid
    """
    if not include_retired:
        sql += " AND retired_at IS NULL"
    sql += " ORDER BY name ASC"
    async with acquire() as conn:
        rows = await conn.fetch(sql, firm_id)
    return [FirmMode.from_row(r) for r in rows]


async def get_firm_mode(firm_id: str, name: str) -> FirmMode | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM firm_modes
            WHERE firm_id = $1::uuid AND name = $2
            """,
            firm_id,
            name,
        )
    return FirmMode.from_row(row) if row else None


async def update_firm_mode(
    *,
    firm_id: str,
    name: str,
    config: dict[str, Any],
    updated_by: str | None,
    actor_email: str | None = None,
) -> FirmMode:
    _validate_overlay_payload(config)
    async with acquire() as conn:
        before = await conn.fetchrow(
            """
            SELECT * FROM firm_modes
            WHERE firm_id = $1::uuid AND name = $2
            """,
            firm_id,
            name,
        )
        if not before:
            raise ModeNotFoundError(
                f"firm mode {name!r} does not exist for firm {firm_id}"
            )
        row = await conn.fetchrow(
            """
            UPDATE firm_modes
            SET config = $3::jsonb, updated_at = NOW()
            WHERE firm_id = $1::uuid AND name = $2
            RETURNING *
            """,
            firm_id,
            name,
            json.dumps(config),
        )

    before_cfg = before["config"]
    if isinstance(before_cfg, str):
        try:
            before_cfg = json.loads(before_cfg)
        except Exception:
            before_cfg = {}
    diff = _config_diff(before_cfg if isinstance(before_cfg, dict) else {}, config)
    await _audit(
        actor_user_id=updated_by,
        actor_email=actor_email,
        action="firm_modes.update",
        firm_id=firm_id,
        mode_name=name,
        payload={"diff": diff},
    )
    invalidate_firm_mode(name, firm_id)
    return FirmMode.from_row(row)


async def retire_firm_mode(
    *,
    firm_id: str,
    name: str,
    retired_by: str | None,
    actor_email: str | None = None,
) -> FirmMode:
    """Soft-delete: marks ``retired_at``. Subsequent resolutions ignore
    the row and fall through to the built-in (or to ``ModeNotFoundError``
    if no built-in exists)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE firm_modes
            SET retired_at = NOW(), updated_at = NOW()
            WHERE firm_id = $1::uuid AND name = $2 AND retired_at IS NULL
            RETURNING *
            """,
            firm_id,
            name,
        )
    if not row:
        raise ModeNotFoundError(
            f"firm mode {name!r} not found or already retired for firm {firm_id}"
        )
    await _audit(
        actor_user_id=retired_by,
        actor_email=actor_email,
        action="firm_modes.retire",
        firm_id=firm_id,
        mode_name=name,
        payload={},
    )
    invalidate_firm_mode(name, firm_id)
    return FirmMode.from_row(row)


async def restore_firm_mode(
    *,
    firm_id: str,
    name: str,
    actor_user_id: str | None,
    actor_email: str | None = None,
) -> FirmMode:
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE firm_modes
            SET retired_at = NULL, updated_at = NOW()
            WHERE firm_id = $1::uuid AND name = $2 AND retired_at IS NOT NULL
            RETURNING *
            """,
            firm_id,
            name,
        )
    if not row:
        raise ModeNotFoundError(
            f"firm mode {name!r} not found or not retired for firm {firm_id}"
        )
    await _audit(
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        action="firm_modes.restore",
        firm_id=firm_id,
        mode_name=name,
        payload={},
    )
    invalidate_firm_mode(name, firm_id)
    return FirmMode.from_row(row)
