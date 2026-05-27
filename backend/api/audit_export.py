"""Audit export — Phase 5 / Week 23 / Day 3.

  - ``GET /api/admin/firms/{id}/audit-export?from=&to=&format=csv|json``
    Streams the firm's audit trail for a date range. Firm-admin
    for own firm; system-admin for any.

Hard rule (W23/D3): the export is content-free. We surface
action + actor + resource ids + timestamp + status — never
claim text, evidence content, memo prose, or any payload the
action might have touched. The audit_events row's ``payload``
JSONB is intentionally light (engagement_id, anchor refs,
counts) — we still pass it through :func:`_strip_payload` as a
second defence so a future writer that puts content into the
payload by mistake doesn't leak it via the export.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from auth.dependencies import get_current_user
from db.connection import acquire

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _is_system_admin(user: dict) -> bool:
    return user.get("role") == "admin"


def _is_firm_admin(user: dict) -> bool:
    return user.get("default_firm_role") == "admin"


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"invalid ISO timestamp: {s!r}",
        )


# ---------------------------------------------------------------------------
# Payload sanitiser — second defence
# ---------------------------------------------------------------------------


# Keys we ALLOW through from the audit_events.payload column.
# Anything not on this list is dropped; in particular, no
# free-form text content (claim/evidence/memo body) leaves the
# export.
_ALLOWED_PAYLOAD_KEYS = {
    "engagement_id", "session_id", "firm_id",
    "anchor_type", "anchor_ref", "review_state",
    "from_state", "to_state", "version_number",
    "task_id", "comment_id", "mention_count",
    "severity", "claim_id", "model", "provider",
    "evidence_object_id", "outcome", "purge_reason",
    "rows_deleted", "files_deleted",
    "threshold_pct", "month_bucket",
}


def _strip_payload(payload: Any) -> dict[str, Any]:
    """Allow-listed copy of the audit payload. Any key not on
    ``_ALLOWED_PAYLOAD_KEYS`` is dropped. The values that do come
    through are coerced to JSON-safe scalars (strings or
    primitives). Nested dicts pass once filtered."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in payload.items():
        if k not in _ALLOWED_PAYLOAD_KEYS:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, dict)):
            # One level of nesting (e.g. anchor_ref). Filter the
            # nested dict the same way; never copy a free-form
            # string value blindly.
            if isinstance(v, dict):
                nested = {
                    nk: nv for nk, nv in v.items()
                    if isinstance(nv, (str, int, float, bool))
                    and nk in _ALLOWED_PAYLOAD_KEYS
                }
                out[k] = nested
            else:
                # List — only retain primitive elements + cap
                # length so a runaway list doesn't bloat the
                # export.
                out[k] = [
                    el for el in v[:50]
                    if isinstance(el, (str, int, float, bool))
                ]
        # Everything else (sets, custom objects, UUIDs) — drop.
    return out


# ---------------------------------------------------------------------------
# Data fetch — firm-scoped audit query
# ---------------------------------------------------------------------------


async def _fetch_audit_rows(
    firm_id: str,
    from_ts: datetime | None,
    to_ts: datetime | None,
    page_size: int = 500,
) -> AsyncIterator[dict[str, Any]]:
    """Iterate the firm's audit_events rows in stable ascending
    id order, paginated by ``page_size``. Audit rows are
    firm-scoped via two paths the existing writers populate:

      - ``payload->>'session_id'`` matches a session in the firm
      - ``resource_id`` matches a session/comment/membership in
        the firm

    Rather than reimplement the lookup chain, we restrict to
    rows whose action class is firm-bounded (engagement / review
    / comment / section / version / task) and JOIN through
    sessions.firm_id when ``payload.session_id`` is present.
    """
    where_parts = [
        "(s.firm_id = $1::uuid)"
    ]
    params: list[Any] = [firm_id]
    if from_ts:
        params.append(from_ts)
        where_parts.append(f"a.created_at >= ${len(params)}")
    if to_ts:
        params.append(to_ts)
        where_parts.append(f"a.created_at < ${len(params)}")
    where = " AND ".join(where_parts)

    last_id = 0
    while True:
        params_with_cursor = params + [last_id, page_size]
        sql = f"""
            SELECT a.id, a.action, a.actor_user_id, a.actor_email,
                   a.resource_type, a.resource_id, a.method, a.path,
                   a.status_code, a.payload, a.created_at
              FROM audit_events a
              LEFT JOIN sessions s
                ON s.id::text = (
                    CASE WHEN a.payload ? 'session_id'
                         THEN a.payload ->> 'session_id'
                         ELSE a.resource_id END
                )
             WHERE {where}
               AND a.id > ${len(params)+1}
             ORDER BY a.id ASC
             LIMIT ${len(params)+2}
        """
        try:
            async with acquire() as conn:
                rows = await conn.fetch(sql, *params_with_cursor)
        except Exception as e:  # noqa: BLE001
            logger.warning("audit export query failed: %s", e)
            return
        if not rows:
            return
        for r in rows:
            last_id = int(r["id"])
            yield {
                "id": int(r["id"]),
                "action": r["action"],
                "actor_user_id": (
                    str(r["actor_user_id"]) if r["actor_user_id"] else None
                ),
                "actor_email": r["actor_email"],
                "resource_type": r["resource_type"],
                "resource_id": r["resource_id"],
                "method": r["method"],
                "path": r["path"],
                "status_code": r["status_code"],
                "payload": _strip_payload(r["payload"]),
                "created_at": (
                    r["created_at"].isoformat() if r["created_at"] else None
                ),
            }
        if len(rows) < page_size:
            return


# ---------------------------------------------------------------------------
# Streamers
# ---------------------------------------------------------------------------


_CSV_FIELDS = [
    "id", "created_at", "action", "actor_user_id", "actor_email",
    "resource_type", "resource_id", "method", "path", "status_code",
    "payload",
]


async def _csv_stream(rows: AsyncIterator[dict[str, Any]]) -> AsyncIterator[bytes]:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS)
    writer.writeheader()
    yield buf.getvalue().encode("utf-8")
    buf.seek(0); buf.truncate(0)
    async for row in rows:
        flat = {k: row.get(k) for k in _CSV_FIELDS}
        # CSV-safe: JSON-encode the payload dict.
        flat["payload"] = json.dumps(flat["payload"]) if flat["payload"] else ""
        writer.writerow(flat)
        yield buf.getvalue().encode("utf-8")
        buf.seek(0); buf.truncate(0)


async def _json_stream(rows: AsyncIterator[dict[str, Any]]) -> AsyncIterator[bytes]:
    """NDJSON — one row per line. Easier to stream + a partial
    download is still a valid line-oriented file."""
    async for row in rows:
        yield (json.dumps(row) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Public route
# ---------------------------------------------------------------------------


@router.get("/firms/{firm_id}/audit-export")
async def export_audit(
    firm_id: str,
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    format: str = Query("csv", regex="^(csv|json)$"),
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the firm's audit trail. CSV or JSON Lines.

    Auth: firm_admin can export their own firm only; system_admin
    can export any. Anyone else → 403."""
    if not (_is_system_admin(user) or _is_firm_admin(user)):
        raise HTTPException(
            status_code=403, detail="Admin role required",
        )
    # Firm-admin locked to own firm; even a ?firm_id=other_firm
    # is denied with 404 (anti-enumeration consistent with W23/D1).
    if (
        _is_firm_admin(user)
        and not _is_system_admin(user)
        and user.get("default_firm_id") != firm_id
    ):
        raise HTTPException(status_code=404, detail="Firm not found")

    from_dt = _parse_iso(from_ts)
    to_dt = _parse_iso(to_ts)

    rows = _fetch_audit_rows(firm_id, from_dt, to_dt)
    if format == "csv":
        return StreamingResponse(
            _csv_stream(rows),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="audit_{firm_id}.csv"'
                ),
            },
        )
    return StreamingResponse(
        _json_stream(rows),
        media_type="application/x-ndjson; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="audit_{firm_id}.ndjson"'
            ),
        },
    )


__all__ = ["router", "_strip_payload"]
