"""Section-deepening accept/reject — Phase 2 / Week 9 / Day 3.

Two terminal actions on a completed deepening:

- :func:`accept_deepening` snapshots the current ``reports`` payload
  onto the deepening row (``pre_accept_payload_snapshot``), uses
  :func:`set_section` to splice the deepened section into the
  current payload, persists the merged payload back to ``reports``,
  marks the deepening row ``accepted_at`` + ``accepted_by``, and
  writes a ``section_deepening.accepted`` audit event.

- :func:`reject_deepening` marks the row ``rejected_at`` +
  ``rejected_by`` and writes ``section_deepening.rejected``. No
  payload change.

Idempotency rule (W9/D3 hard rule "don't let accept fire twice"):
if ``accepted_at`` is already set on the row, accept short-circuits
and returns the existing state — the second caller sees a
no-op, not a 409. Same for reject.

History preservation: the full pre-accept payload is captured in
``pre_accept_payload_snapshot`` so a future rollback / version-
history UI (Phase 4) can reconstruct the prior memo. The
``reports`` table itself stays single-row-per-session — no
breaking change for readers that assume ``reports.session_id``
unique-key access.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from db.connection import acquire

from .addressing import SectionNotFoundError, set_section

logger = logging.getLogger(__name__)


class DeepeningNotFoundError(LookupError):
    """Raised when the deepening_id / session_id pair doesn't resolve."""


class DeepeningNotAcceptableError(ValueError):
    """Raised when the row exists but isn't in a state that allows
    acceptance (not complete, already rejected, etc.). Idempotency
    on a previous accept is NOT this error — that case returns
    silently."""


# ---------------------------------------------------------------------------
# Internal: payload load/save — mirrors service.py's ``_load_report_payload``
# but keeps the original column shape so we can reseat individual fields.
# ---------------------------------------------------------------------------


_BASE_COLUMNS: tuple[str, ...] = (
    "recommendation",
    "confidence_level",
    "summary",
    "key_reasons",
    "risks",
    "counterarguments",
    "next_steps",
    "sources",
    "caveats",
)


async def _load_full_payload(session_id: UUID) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return ``(merged_payload, raw_row)`` for the session's report row.

    ``merged_payload`` is the dotted-path-addressable shape used by
    :func:`set_section`; ``raw_row`` retains each column's value so
    we can write back column-by-column on accept.
    """
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
        return None
    raw = {k: row[k] for k in row.keys()}
    cp = raw.get("consulting_payload")
    if isinstance(cp, str):
        try:
            cp = json.loads(cp)
        except Exception:
            cp = {}
    raw["consulting_payload"] = cp if isinstance(cp, dict) else {}

    merged: dict[str, Any] = {k: raw[k] for k in _BASE_COLUMNS}
    merged.update(raw["consulting_payload"])
    return merged, raw


async def _persist_merged_payload(
    session_id: UUID,
    merged: dict[str, Any],
    raw: dict[str, Any],
) -> None:
    """Write the merged payload back to ``reports`` column-by-column.

    Base fields (recommendation, summary, etc.) come from the merged
    top-level keys; everything else lands in ``consulting_payload``.
    ``reports.raw_output`` is left untouched (it's the original LLM
    response; the deepening produced a section-level rewrite, not a
    new full-memo output).
    """
    # Split merged into base columns vs consulting_payload extras.
    new_base = {k: merged.get(k, raw.get(k)) for k in _BASE_COLUMNS}
    new_cp = {k: v for k, v in merged.items() if k not in _BASE_COLUMNS}

    # asyncpg needs lists/dicts JSON-encoded for jsonb columns; text
    # columns pass through as-is. Pydantic-validated base list types
    # (key_reasons / risks / ...) are stored as jsonb in the schema.
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE reports SET
                recommendation = $2,
                confidence_level = $3,
                summary = $4,
                key_reasons = $5::jsonb,
                risks = $6::jsonb,
                counterarguments = $7::jsonb,
                next_steps = $8::jsonb,
                sources = $9::jsonb,
                caveats = $10,
                consulting_payload = $11::jsonb
            WHERE session_id = $1::uuid
            """,
            session_id,
            str(new_base["recommendation"] or ""),
            str(new_base["confidence_level"] or ""),
            str(new_base["summary"] or ""),
            json.dumps(new_base["key_reasons"] or []),
            json.dumps(new_base["risks"] or []),
            json.dumps(new_base["counterarguments"] or []),
            json.dumps(new_base["next_steps"] or []),
            json.dumps(new_base["sources"] or []),
            str(new_base["caveats"] or ""),
            json.dumps(new_cp),
        )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


async def _write_audit(
    action: str,
    actor_user_id: UUID | None,
    deepening_id: UUID,
    payload: dict[str, Any],
) -> None:
    """Append one ``audit_events`` row. Best-effort — never raises;
    an audit-log hiccup must not prevent the user-facing accept/
    reject from landing."""
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_events
                  (actor_user_id, action, resource_type, resource_id, payload)
                VALUES
                  ($1::uuid, $2, 'section_deepening', $3, $4::jsonb)
                """,
                actor_user_id,
                action,
                str(deepening_id),
                json.dumps(payload),
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("audit insert skipped for %s/%s: %s", action, deepening_id, e)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def accept_deepening(
    session_id: UUID,
    deepening_id: UUID,
    accepted_by: UUID,
) -> dict[str, Any]:
    """Apply a completed deepening to the session's current report
    payload and record the acceptance.

    Returns a dict shaped for the API layer to send back to the
    consultant — ``{deepening_id, status, accepted_at,
    new_payload}``. Idempotent: a second call on an already-accepted
    row returns the prior state without re-mutating anything.

    Raises:
      - :class:`DeepeningNotFoundError` if the row doesn't exist
        for this session.
      - :class:`DeepeningNotAcceptableError` if the row's status
        isn't ``complete`` (queued/running/failed/rejected are
        non-acceptable).
      - :class:`SectionNotFoundError` if the deepening's
        ``section_path`` no longer resolves against the current
        payload (the memo drifted in the meantime — fail loudly so
        the consultant re-fires).
    """
    # Load deepening row.
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, section_path, status, accepted_at,
                   rejected_at, deepened_section_json
            FROM section_deepening_runs
            WHERE id = $1::uuid AND session_id = $2::uuid
            """,
            deepening_id,
            session_id,
        )
    if not row:
        raise DeepeningNotFoundError(
            f"deepening {deepening_id} not found for session {session_id}"
        )

    # Idempotent short-circuit.
    if row["accepted_at"] is not None:
        return {
            "deepening_id": str(deepening_id),
            "status": "already_accepted",
            "accepted_at": row["accepted_at"].isoformat(),
        }
    if row["rejected_at"] is not None:
        raise DeepeningNotAcceptableError(
            f"deepening {deepening_id} was rejected — cannot accept"
        )
    if row["status"] != "complete":
        raise DeepeningNotAcceptableError(
            f"deepening {deepening_id} has status {row['status']!r}; "
            f"only ``complete`` deepenings can be accepted"
        )

    section_path = str(row["section_path"])
    deepened_section = row["deepened_section_json"]
    if isinstance(deepened_section, str):
        try:
            deepened_section = json.loads(deepened_section)
        except Exception:
            deepened_section = None

    loaded = await _load_full_payload(session_id)
    if loaded is None:
        raise DeepeningNotAcceptableError(
            f"session {session_id} has no report row to merge into"
        )
    merged, raw = loaded

    # Snapshot the pre-accept payload BEFORE mutating reports — this
    # is the history-preservation trail. The original_section_json
    # captured at deepening-request time is for "did the section
    # drift between request and accept"; the snapshot here captures
    # the entire current memo state at accept time.
    snapshot = dict(merged)

    # Apply the deepened section to the merged payload. If the path
    # doesn't resolve, the consultant's memo drifted; surface the
    # error rather than silently dropping the deepening.
    new_payload = set_section(merged, section_path, deepened_section)

    # Persist the merged payload column-by-column.
    await _persist_merged_payload(session_id, new_payload, raw)

    # Mark the deepening row accepted + carry the snapshot.
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE section_deepening_runs SET
                accepted_at = NOW(),
                accepted_by = $2::uuid,
                pre_accept_payload_snapshot = $3::jsonb
            WHERE id = $1::uuid AND accepted_at IS NULL
            """,
            deepening_id,
            accepted_by,
            json.dumps(snapshot),
        )

    await _write_audit(
        "section_deepening.accepted",
        accepted_by,
        deepening_id,
        {
            "session_id": str(session_id),
            "section_path": section_path,
        },
    )

    return {
        "deepening_id": str(deepening_id),
        "status": "accepted",
        "section_path": section_path,
        "new_payload": new_payload,
    }


async def reject_deepening(
    session_id: UUID,
    deepening_id: UUID,
    rejected_by: UUID,
) -> dict[str, Any]:
    """Mark the deepening rejected and write an audit event.

    Idempotent: a second reject on an already-rejected row returns
    the prior state. A reject on an already-accepted row raises
    :class:`DeepeningNotAcceptableError`.
    """
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, section_path, accepted_at, rejected_at, status
            FROM section_deepening_runs
            WHERE id = $1::uuid AND session_id = $2::uuid
            """,
            deepening_id,
            session_id,
        )
    if not row:
        raise DeepeningNotFoundError(
            f"deepening {deepening_id} not found for session {session_id}"
        )
    if row["accepted_at"] is not None:
        raise DeepeningNotAcceptableError(
            f"deepening {deepening_id} was already accepted — cannot reject"
        )
    if row["rejected_at"] is not None:
        return {
            "deepening_id": str(deepening_id),
            "status": "already_rejected",
            "rejected_at": row["rejected_at"].isoformat(),
        }

    section_path = str(row["section_path"])

    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE section_deepening_runs SET
                rejected_at = NOW(),
                rejected_by = $2::uuid
            WHERE id = $1::uuid AND rejected_at IS NULL AND accepted_at IS NULL
            """,
            deepening_id,
            rejected_by,
        )

    await _write_audit(
        "section_deepening.rejected",
        rejected_by,
        deepening_id,
        {
            "session_id": str(session_id),
            "section_path": section_path,
        },
    )

    return {
        "deepening_id": str(deepening_id),
        "status": "rejected",
        "section_path": section_path,
    }
