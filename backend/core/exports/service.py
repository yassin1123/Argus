"""Export service — W10/D2.

Loads payload + firm branding, builds citations, dispatches via
:func:`get_exporter`, persists file to disk, writes the
``export_artifacts`` row. The API endpoints in ``backend/api/exports.py``
are thin wrappers over this module.

Storage: files land under ``ARGUS_ARTIFACTS_ROOT`` (default
``/tmp/argus_artifacts`` on POSIX, ``%TEMP%/argus_artifacts`` on
Windows), partitioned by firm/session/artifact:
``<root>/<firm_id>/<session_id>/<artifact_id>.<format>``.
Phase 5 swaps this for S3/blob.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from db.connection import acquire

from ._base import ClaimCitation
from ._registry import get_exporter, list_registered

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants + helpers
# ---------------------------------------------------------------------------


def _artifacts_root() -> Path:
    """Root directory for rendered artifact files.

    Resolved at call time (not import time) so tests can override via
    the ``ARGUS_ARTIFACTS_ROOT`` env var.
    """
    env = os.environ.get("ARGUS_ARTIFACTS_ROOT")
    if env:
        return Path(env)
    # Cross-platform default: gettempdir gives /tmp on POSIX, %TEMP%
    # on Windows. Keep the directory name stable across runs.
    return Path(tempfile.gettempdir()) / "argus_artifacts"


def artifact_file_path(firm_id: UUID, session_id: UUID, artifact_id: UUID, format: str) -> Path:
    """Resolve the on-disk path for a (firm, session, artifact, format)."""
    return _artifacts_root() / str(firm_id) / str(session_id) / f"{artifact_id}.{format}"


# ---------------------------------------------------------------------------
# Public DTOs
# ---------------------------------------------------------------------------


@dataclass
class GenerateArtifactRequest:
    session_id: UUID
    artifact_type: str
    format: str


@dataclass
class GenerateArtifactResult:
    artifact_id: UUID
    session_id: UUID
    artifact_type: str
    format: str
    status: str  # 'ready' | 'failed'
    file_path: str | None = None
    file_size_bytes: int | None = None
    claim_citation_count: int = 0
    generation_wall_seconds: float = 0.0
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ArtifactNotFoundError(Exception):
    """Raised when an artifact id is missing or scoped to another session."""


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _firm_id_for_session(session_id: UUID) -> UUID | None:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT firm_id FROM sessions WHERE id = $1::uuid", session_id
        )
    return row["firm_id"] if row else None


async def _session_meta(session_id: UUID) -> dict[str, Any]:
    """Pull session-level metadata used to populate the artifact header
    (title, target name, mode hint). Best-effort: keys may be missing
    on older sessions, in which case the renderer falls back to
    generic defaults."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT title, query, report_mode, metadata
            FROM sessions WHERE id = $1::uuid
            """,
            session_id,
        )
    if not row:
        return {}
    out: dict[str, Any] = {
        "title": row["title"] or "",
        "report_mode": row["report_mode"] or "",
    }
    md = row["metadata"]
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except Exception:
            md = {}
    if isinstance(md, dict):
        out["target_name"] = str(
            md.get("target_name") or md.get("target") or ""
        )
    return out


async def _firm_branding(firm_id: UUID) -> dict[str, Any]:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT name, branding FROM firms WHERE id = $1::uuid", firm_id
        )
    if not row:
        return {}
    b = row["branding"]
    if isinstance(b, str):
        try:
            b = json.loads(b) or {}
        except Exception:
            b = {}
    out = dict(b or {})
    # ``firm_name`` is not formally part of the branding JSONB but the
    # renderer wants it for the header fallback when logo_url is empty.
    out.setdefault("_firm_name", row["name"] or "Argus")
    return out


def _decode_jsonb(v: Any) -> Any:
    """asyncpg returns jsonb as str by default in this project's
    connection setup. Decode it to native Python; pass-through if
    already a list/dict/None."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


async def _load_payload(session_id: UUID) -> dict[str, Any] | None:
    """Pull the writer payload from ``reports``. Merged shape:
    base WriterReportBase fields + consulting_payload. All jsonb
    columns are decoded so downstream consumers see lists/dicts, not
    raw JSON strings."""
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
    out: dict[str, Any] = {}
    for k in row.keys():
        if k == "consulting_payload":
            continue
        v = row[k]
        # The 4 list-shaped columns + sources arrive as jsonb; decode.
        if k in ("key_reasons", "risks", "counterarguments", "next_steps", "sources"):
            v = _decode_jsonb(v)
        out[k] = v
    cp = _decode_jsonb(row["consulting_payload"])
    if isinstance(cp, dict):
        out.update(cp)
    return out


def _payload_fingerprint(payload: dict[str, Any] | None) -> str:
    """Stable hash of the writer-derived parts of a payload.

    Excludes underscore-prefixed engagement keys (``_engagement_title``,
    ``_target_name``, etc.) — those are session-derived metadata, not
    writer output, so a session title rename shouldn't make every prior
    artifact look "stale". Also sorts list contents so cosmetic reorders
    in ``sources``/``key_reasons``/etc. don't trigger false positives.
    """
    import hashlib

    if not isinstance(payload, dict):
        return ""
    keep: dict[str, Any] = {}
    for k, v in payload.items():
        if not isinstance(k, str) or k.startswith("_"):
            continue
        keep[k] = _canonicalise(v)
    # ``key_reasons`` / ``risks`` / ``sources`` arrive as lists; sort
    # them so ordering changes don't trip the diff.
    for k in ("key_reasons", "risks", "counterarguments", "next_steps", "sources"):
        v = keep.get(k)
        if isinstance(v, list):
            try:
                keep[k] = sorted(v, key=lambda x: json.dumps(x, sort_keys=True))
            except TypeError:
                keep[k] = v
    blob = json.dumps(keep, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _canonicalise(value: Any) -> Any:
    """Recursively turn dict/list/scalar trees into a comparable shape.

    Strips whitespace at the edges of strings so trailing whitespace
    in a key_reason doesn't show up as a fresh fingerprint.
    """
    if isinstance(value, dict):
        return {k: _canonicalise(v) for k, v in value.items() if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(value, list):
        return [_canonicalise(v) for v in value]
    if isinstance(value, str):
        return value.strip()
    return value


async def _available_artifacts_for_email(
    session_id: UUID,
    current_payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return the list of READY artifacts for the session (excluding
    ``email`` itself) annotated with stale flags.

    Used by ``generate_artifact`` when rendering an email artifact —
    the email then references real attachments rather than the
    hardcoded mode-default placeholder.
    """
    fp_current = _payload_fingerprint(current_payload)
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, artifact_type, format, file_size_bytes,
                   claim_citation_count, generated_at, metadata,
                   payload_snapshot
            FROM export_artifacts
            WHERE session_id = $1::uuid
              AND status = 'ready'
              AND artifact_type <> 'email'
            ORDER BY artifact_type, format, generated_at DESC
            """,
            session_id,
        )
    out: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row["artifact_type"]), str(row["format"]))
        # Dedup multiple regenerations of the same (type, format): the
        # newest wins because the ORDER BY puts it first.
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        snap = _decode_jsonb(row["payload_snapshot"])
        fp_snap = _payload_fingerprint(snap) if isinstance(snap, dict) else ""
        is_stale = bool(fp_current and fp_snap and fp_snap != fp_current)
        md = _decode_jsonb(row["metadata"]) or {}
        out.append({
            "artifact_id": str(row["id"]),
            "artifact_type": row["artifact_type"],
            "format": row["format"],
            "file_size_bytes": row["file_size_bytes"],
            "claim_citation_count": row["claim_citation_count"],
            "generated_at": row["generated_at"],
            "metadata": md if isinstance(md, dict) else {},
            "is_stale": is_stale,
        })
    return out


async def _build_citations(session_id: UUID) -> list[ClaimCitation]:
    """Build the citation list from the latest analyst output + evidence
    catalog. Best-effort: if the analyst row is missing or the shape
    is unexpected, return an empty list — the exporter can still
    render the recommendation without footnotes."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT output FROM agent_outputs
            WHERE session_id = $1::uuid
              AND agent_name IN ('analyst_revision', 'analyst')
            ORDER BY CASE agent_name WHEN 'analyst_revision' THEN 0 ELSE 1 END,
                     created_at DESC
            LIMIT 1
            """,
            session_id,
        )
        evs = await conn.fetch(
            """
            SELECT id, source_title, source_type
            FROM evidence_objects WHERE session_id = $1::uuid
            """,
            session_id,
        )
    if not row:
        return []
    try:
        analysis = json.loads(row["output"]) if isinstance(row["output"], str) else row["output"]
    except Exception:
        return []
    ev_map: dict[str, tuple[str, str]] = {
        str(e["id"]): (str(e["source_title"] or ""), str(e["source_type"] or ""))
        for e in evs
    }
    out: list[ClaimCitation] = []
    for c in (analysis or {}).get("key_claims") or []:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("claim_id") or "")
        if not cid:
            continue
        ev_ids = c.get("evidence_ids") or []
        title, stype = "", ""
        for eid in ev_ids:
            if str(eid) in ev_map:
                title, stype = ev_map[str(eid)]
                break
        out.append(
            ClaimCitation(
                claim_id=cid,
                text=str(c.get("text") or ""),
                source_title=title,
                source_type=stype,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Persistence: row insert + transitions
# ---------------------------------------------------------------------------


async def _insert_generating_row(
    artifact_id: UUID,
    session_id: UUID,
    firm_id: UUID,
    artifact_type: str,
    format: str,
    payload_snapshot: dict[str, Any] | None,
    triggered_by: UUID | None,
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO export_artifacts (
                id, session_id, firm_id, artifact_type, format,
                payload_snapshot, generated_by, status
            ) VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5,
                      $6::jsonb, $7, 'generating')
            """,
            artifact_id,
            session_id,
            firm_id,
            artifact_type,
            format,
            json.dumps(payload_snapshot) if payload_snapshot is not None else None,
            triggered_by,
        )


async def _mark_ready(
    artifact_id: UUID,
    *,
    file_path: str,
    file_size: int,
    claim_citation_count: int,
    wall_seconds: float,
    metadata: dict[str, Any],
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE export_artifacts
            SET status = 'ready',
                file_path = $2,
                file_size_bytes = $3,
                claim_citation_count = $4,
                generation_wall_seconds = $5,
                metadata = $6::jsonb
            WHERE id = $1::uuid
            """,
            artifact_id,
            file_path,
            file_size,
            claim_citation_count,
            wall_seconds,
            json.dumps(metadata or {}),
        )


async def _mark_failed(artifact_id: UUID, reason: str, wall_seconds: float) -> None:
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE export_artifacts
            SET status = 'failed',
                failure_reason = $2,
                generation_wall_seconds = $3
            WHERE id = $1::uuid
            """,
            artifact_id,
            reason[:2000],
            wall_seconds,
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def generate_artifact(
    request: GenerateArtifactRequest,
    triggered_by: UUID | None = None,
) -> GenerateArtifactResult:
    """End-to-end: load payload + branding + citations, dispatch exporter,
    write file, persist row.

    The row exists in ``status='generating'`` from the moment we accept
    the request — the API can return the id immediately and the GET
    endpoint will see the row whether the render is mid-flight, ready,
    or failed.
    """
    t0 = time.perf_counter()
    artifact_id = uuid.uuid4()
    session_id = request.session_id
    artifact_type = request.artifact_type
    format = request.format

    firm_id = await _firm_id_for_session(session_id)
    if firm_id is None:
        return GenerateArtifactResult(
            artifact_id=artifact_id,
            session_id=session_id,
            artifact_type=artifact_type,
            format=format,
            status="failed",
            failure_reason=f"session {session_id} not found or has no firm_id",
            generation_wall_seconds=time.perf_counter() - t0,
        )

    exporter = get_exporter(artifact_type, format)
    if exporter is None:
        # Insert a failed row anyway so the caller can poll for it and
        # see a clear reason instead of a silent dropped POST.
        await _insert_generating_row(
            artifact_id,
            session_id,
            firm_id,
            artifact_type,
            format,
            payload_snapshot=None,
            triggered_by=triggered_by,
        )
        reason = (
            f"no exporter registered for ({artifact_type!r}, {format!r}); "
            f"available: {list_registered()}"
        )
        await _mark_failed(artifact_id, reason, time.perf_counter() - t0)
        return GenerateArtifactResult(
            artifact_id=artifact_id,
            session_id=session_id,
            artifact_type=artifact_type,
            format=format,
            status="failed",
            failure_reason=reason,
            generation_wall_seconds=time.perf_counter() - t0,
        )

    payload = await _load_payload(session_id) or {}
    branding = await _firm_branding(firm_id)
    citations = await _build_citations(session_id)
    sess = await _session_meta(session_id)

    # Inject engagement metadata onto the payload under reserved
    # underscore-prefixed keys. The exporter reads these for the
    # header and mode hint; they're not part of the writer schema and
    # don't pollute the frozen snapshot semantically (they're
    # session-derived, not writer-derived).
    payload.setdefault("_engagement_title", sess.get("title") or "Argus 1-pager")
    payload.setdefault("_mode_hint", sess.get("report_mode") or None)
    payload.setdefault("_target_name", sess.get("target_name") or "")
    payload.setdefault("_firm_name", branding.get("_firm_name") or "Argus")
    if triggered_by:
        payload.setdefault("_prepared_by", str(triggered_by))

    # W13/D2: when rendering an email, attach the list of already-ready
    # artifacts for the same session so the EmailBuilder references
    # real attachments instead of the mode-default placeholder. The
    # builder's stale-flagging logic uses ``is_stale`` per row.
    if artifact_type == "email":
        available = await _available_artifacts_for_email(session_id, payload)
        payload["_available_artifacts"] = available

    await _insert_generating_row(
        artifact_id,
        session_id,
        firm_id,
        artifact_type,
        format,
        payload_snapshot=payload,  # freeze it here
        triggered_by=triggered_by,
    )

    try:
        result = await exporter.render(
            payload or {},
            branding,
            citations,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception(
            "exporter %s/%s failed for session %s", artifact_type, format, session_id
        )
        wall = time.perf_counter() - t0
        await _mark_failed(artifact_id, f"render error: {e}", wall)
        return GenerateArtifactResult(
            artifact_id=artifact_id,
            session_id=session_id,
            artifact_type=artifact_type,
            format=format,
            status="failed",
            failure_reason=f"render error: {e}",
            generation_wall_seconds=wall,
        )

    # Persist file to disk.
    fpath = artifact_file_path(firm_id, session_id, artifact_id, format)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_bytes(result.file_bytes)

    wall = time.perf_counter() - t0
    await _mark_ready(
        artifact_id,
        file_path=str(fpath),
        file_size=result.file_size,
        claim_citation_count=result.claim_citation_count,
        wall_seconds=wall,
        metadata=result.metadata or {},
    )

    return GenerateArtifactResult(
        artifact_id=artifact_id,
        session_id=session_id,
        artifact_type=artifact_type,
        format=format,
        status="ready",
        file_path=str(fpath),
        file_size_bytes=result.file_size,
        claim_citation_count=result.claim_citation_count,
        generation_wall_seconds=wall,
        metadata=result.metadata or {},
    )


# ---------------------------------------------------------------------------
# Read helpers (API consumers)
# ---------------------------------------------------------------------------


async def get_artifact(session_id: UUID, artifact_id: UUID) -> dict[str, Any] | None:
    """Fetch a single artifact row scoped to ``session_id`` (so an
    artifact for session A is invisible when queried against session B
    — the API layer also enforces firm-tier permissions on top)."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, firm_id, artifact_type, format,
                   file_path, file_size_bytes, claim_citation_count,
                   generation_cost_usd, generation_wall_seconds,
                   generated_by, generated_at, metadata, status,
                   failure_reason
            FROM export_artifacts
            WHERE id = $1::uuid AND session_id = $2::uuid
            """,
            artifact_id,
            session_id,
        )
    if not row:
        return None
    out = dict(row)
    md = out.get("metadata")
    if isinstance(md, str):
        try:
            out["metadata"] = json.loads(md)
        except Exception:
            out["metadata"] = {}
    return out


async def list_artifacts(session_id: UUID) -> list[dict[str, Any]]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, artifact_type, format, status, file_size_bytes,
                   claim_citation_count, generation_wall_seconds,
                   generated_at, failure_reason
            FROM export_artifacts
            WHERE session_id = $1::uuid
            ORDER BY generated_at DESC
            """,
            session_id,
        )
    return [dict(r) for r in rows]
