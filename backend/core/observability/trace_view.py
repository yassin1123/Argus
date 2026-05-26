"""Trace-view assembler — Phase 5 / Week 20 / Day 4.

For one engagement, joins everything we already record
(pipeline_trace events, llm_calls, cost_ledger, metric_events,
sessions metadata, payload_versions) into a single structured
view so an operator can answer "what happened here" in one
request — costs, durations, verdicts, retrieval shape, the
failure if there was one.

The assembler **reads only**. It re-runs nothing. A missing
table or empty join doesn't crash it — every section degrades
gracefully and is flagged in :attr:`EngagementTrace.gaps` so
the UI can surface where data is missing rather than silently
report zeros.

Hard rule (matches W20/D1 redaction): no claim text, no
evidence content, no memo prose lands in the trace. The trace
is shape + metadata + IDs + counts. The actual content is
behind separate access-controlled endpoints (W4/W9/W14
deliverables, W19 version history); the trace links by ID,
never inlines.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from db.connection import acquire

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


# Canonical stage order used to sort timeline rows when the
# pipeline_trace events are out of order or partial. Mirrors the
# orchestrator's actual sequence (W7-era + W20/D1 instrumentation).
_STAGE_ORDER = [
    "pipeline_start",
    "plan_ready",
    "research_gathered",
    "analysis_v1_done",
    "critique_done",
    "analysis_v2_done",
    "verification_done",
    "evidence_insufficient",
    "gates_validated",
    "critic_post_done",
    "deliverable_ready",
    "complete",
    "failed",
]


@dataclass
class TimelineStage:
    """One row in the lifecycle timeline."""

    stage: str
    at: str | None = None
    duration_ms: float | None = None
    detail: str | None = None
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMCallRow:
    """One LLM call as it appeared in ``llm_calls``."""

    agent: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    success: bool = True
    error_kind: str | None = None
    at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StageRollup:
    """LLM-call rollup for one ``agent`` (≈ stage)."""

    agent: str
    call_count: int = 0
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationSummary:
    """Verifier rollup: how the claims landed."""

    assessments_total: int = 0
    verdict_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RetrievalSummary:
    """Retrieval rollup: where the evidence came from."""

    evidence_count: int = 0
    evidence_by_source: dict[str, int] = field(default_factory=dict)
    followup_query_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FailureRecord:
    """Failure diagnosis surface for a failed engagement."""

    failed: bool = False
    failed_stage: str | None = None
    last_successful_stage: str | None = None
    error_message: str | None = None
    error_kind: str | None = None
    writer_schema_failure: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngagementTrace:
    """The top-level view returned to the API."""

    session_id: str
    firm_id: str | None = None
    run_id: str | None = None
    status: str | None = None
    pipeline_state: str | None = None
    report_mode: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    wall_ms: float | None = None
    total_cost_usd: float = 0.0
    timeline: list[TimelineStage] = field(default_factory=list)
    stage_rollups: list[StageRollup] = field(default_factory=list)
    llm_calls: list[LLMCallRow] = field(default_factory=list)
    verification: VerificationSummary = field(default_factory=VerificationSummary)
    retrieval: RetrievalSummary = field(default_factory=RetrievalSummary)
    versions: list[dict[str, Any]] = field(default_factory=list)
    failure: FailureRecord = field(default_factory=FailureRecord)
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "firm_id": self.firm_id,
            "run_id": self.run_id,
            "status": self.status,
            "pipeline_state": self.pipeline_state,
            "report_mode": self.report_mode,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "wall_ms": self.wall_ms,
            "total_cost_usd": self.total_cost_usd,
            "timeline": [s.to_dict() for s in self.timeline],
            "stage_rollups": [r.to_dict() for r in self.stage_rollups],
            "llm_calls": [c.to_dict() for c in self.llm_calls],
            "verification": self.verification.to_dict(),
            "retrieval": self.retrieval.to_dict(),
            "versions": self.versions,
            "failure": self.failure.to_dict(),
            "gaps": self.gaps,
        }


# ---------------------------------------------------------------------------
# Internal section assemblers
# ---------------------------------------------------------------------------


_SUCCESS_TERMINAL = {"complete", "deliverable_ready"}
_FAILURE_TERMINAL = {"failed"}


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


async def _load_session_view(session_id: str) -> dict[str, Any] | None:
    """Pull the session row + its metadata.pipeline_trace + report_mode +
    status fields. Returns ``None`` when the session doesn't exist —
    the API layer maps that to 404."""
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, firm_id, status, pipeline_state, report_mode,
                       metadata, created_at, updated_at
                  FROM sessions WHERE id = $1::uuid
                """,
                session_id,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("trace: session lookup failed: %s", e)
        return None
    if not row:
        return None
    meta = row["metadata"]
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return {
        "id": str(row["id"]),
        "firm_id": str(row["firm_id"]) if row["firm_id"] else None,
        "status": row["status"],
        "pipeline_state": row["pipeline_state"],
        "report_mode": row["report_mode"],
        "metadata": meta or {},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _build_timeline(events: list[dict[str, Any]]) -> list[TimelineStage]:
    """Convert pipeline_trace event dicts → timeline rows with
    per-stage durations (delta from previous event's ``at``).
    Tolerates missing or unparseable ``at`` timestamps — those
    rows just don't carry a duration."""
    if not events:
        return []
    rows: list[TimelineStage] = []
    prev_dt: datetime | None = None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        at = ev.get("at")
        dt = _parse_iso(at) if isinstance(at, str) else None
        duration_ms: float | None = None
        if dt is not None and prev_dt is not None:
            duration_ms = (dt - prev_dt).total_seconds() * 1000.0
        stage_name = str(ev.get("event") or "unknown")
        rows.append(TimelineStage(
            stage=stage_name,
            at=at if isinstance(at, str) else None,
            duration_ms=duration_ms,
            detail=str(ev.get("detail") or "") or None,
            ok=stage_name not in _FAILURE_TERMINAL,
        ))
        if dt is not None:
            prev_dt = dt
    return rows


async def _load_llm_calls(session_id: str) -> list[LLMCallRow]:
    """Read ``llm_calls`` rows for the session. The Phase 7 table is
    the per-call audit row; cost_ledger is the per-call cost row.
    They mirror each other today, but llm_calls also carries
    ``success`` + ``error_kind`` which are the source of the
    per-stage error-count rollup."""
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT task_kind, model, provider, prompt_tokens,
                       completion_tokens, usd_cost, latency_ms,
                       success, error_kind, created_at
                  FROM llm_calls WHERE session_id = $1::uuid
                  ORDER BY created_at ASC
                """,
                session_id,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("trace: llm_calls lookup failed: %s", e)
        return []
    out: list[LLMCallRow] = []
    for r in rows:
        out.append(LLMCallRow(
            agent=str(r["task_kind"] or "unknown"),
            provider=str(r["provider"] or "unknown"),
            model=str(r["model"] or "unknown"),
            prompt_tokens=int(r["prompt_tokens"] or 0),
            completion_tokens=int(r["completion_tokens"] or 0),
            cost_usd=float(r["usd_cost"] or 0.0),
            latency_ms=int(r["latency_ms"] or 0),
            success=bool(r["success"]),
            error_kind=str(r["error_kind"]) if r["error_kind"] else None,
            at=r["created_at"].isoformat() if r["created_at"] else None,
        ))
    return out


def _rollup_by_agent(calls: list[LLMCallRow]) -> list[StageRollup]:
    """Group LLM calls by agent (= task_kind / stage) and produce
    one row per agent with totals. Used both for the per-stage
    cost view and as the cross-check against cost_ledger."""
    by: dict[str, StageRollup] = {}
    for c in calls:
        r = by.get(c.agent) or StageRollup(agent=c.agent)
        r.call_count += 1
        r.cost_usd += c.cost_usd
        r.prompt_tokens += c.prompt_tokens
        r.completion_tokens += c.completion_tokens
        if not c.success:
            r.error_count += 1
        by[c.agent] = r
    return sorted(by.values(), key=lambda r: r.cost_usd, reverse=True)


async def _load_verification_summary(
    session_id: str,
) -> VerificationSummary:
    """Pull verifier verdict counts from the W20/D2 metric_events
    (``verification.verdict`` counter). Falls back to the session
    metadata's verifier output when metrics are unavailable."""
    out = VerificationSummary()
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT labels ->> 'outcome' AS outcome,
                       COALESCE(SUM(value), 0)::int AS n
                  FROM metric_events
                 WHERE metric_name = 'verification.verdict'
                   AND (
                        labels ->> 'session_id' = $1::text
                        OR id IN (
                            SELECT id FROM metric_events
                             WHERE metric_name = 'verification.verdict'
                               AND trace_id IN (
                                   SELECT trace_id FROM metric_events
                                    WHERE labels ->> 'session_id' = $1::text
                                      AND trace_id IS NOT NULL
                                    LIMIT 1
                               )
                        )
                   )
                 GROUP BY outcome
                """,
                session_id,
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("trace: verification rollup failed: %s", e)
        return out
    dist: dict[str, int] = {}
    for r in rows:
        if r["outcome"]:
            dist[str(r["outcome"])] = int(r["n"])
    out.verdict_distribution = dist
    out.assessments_total = sum(dist.values())
    return out


async def _load_retrieval_summary(
    session_id: str, session_meta: dict[str, Any],
) -> RetrievalSummary:
    """Pull retrieval breakdown from the W20/D2 ``retrieval.hits``
    counter; falls back to ``sessions.metadata.retrieval_hits``
    when metrics are missing."""
    out = RetrievalSummary()
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT labels ->> 'source_type' AS source,
                       COALESCE(SUM(value), 0)::int AS n
                  FROM metric_events
                 WHERE metric_name = 'retrieval.hits'
                   AND labels ->> 'session_id' = $1::text
                 GROUP BY source
                """,
                session_id,
            )
    except Exception:  # noqa: BLE001
        rows = []
    by_src: dict[str, int] = {}
    for r in rows or []:
        if r["source"]:
            by_src[str(r["source"])] = int(r["n"])
    if not by_src and isinstance(session_meta, dict):
        # Fallback to the denormalised hit map the orchestrator
        # writes alongside research_gathered.
        rh = session_meta.get("retrieval_hits")
        if isinstance(rh, dict):
            for k, v in rh.items():
                try:
                    by_src[str(k)] = int(v)
                except (TypeError, ValueError):
                    continue
    out.evidence_by_source = by_src
    out.evidence_count = sum(by_src.values())
    fc = session_meta.get("followup_query_count") if isinstance(session_meta, dict) else None
    try:
        out.followup_query_count = int(fc) if fc is not None else 0
    except (TypeError, ValueError):
        out.followup_query_count = 0
    return out


async def _load_versions(session_id: str) -> list[dict[str, Any]]:
    """Pull the W19 payload_versions for review history. ID +
    change_type + change_summary + review_state — no prose."""
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT version_number, change_type, change_summary,
                       review_state_at_version, created_at, created_by
                  FROM payload_versions
                 WHERE session_id = $1::uuid
                 ORDER BY version_number ASC
                """,
                session_id,
            )
    except Exception:  # noqa: BLE001
        return []
    return [
        {
            "version_number": int(r["version_number"]),
            "change_type": r["change_type"],
            "change_summary": r["change_summary"],
            "review_state": r["review_state_at_version"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "created_by": str(r["created_by"]) if r["created_by"] else None,
        }
        for r in rows
    ]


def _diagnose_failure(
    timeline: list[TimelineStage],
    session_meta: dict[str, Any],
    llm_calls: list[LLMCallRow],
) -> FailureRecord:
    """Reconstruct a FailureRecord from the timeline + session
    metadata + LLM call errors. A failed engagement is one whose
    last terminal event is ``failed`` OR whose session.status =
    ``failed``."""
    rec = FailureRecord()
    failed_evt = None
    last_ok = None
    for ev in timeline:
        if ev.stage in _FAILURE_TERMINAL:
            failed_evt = ev
            break
        if ev.stage not in _FAILURE_TERMINAL:
            last_ok = ev.stage
    if failed_evt is None:
        return rec
    rec.failed = True
    rec.failed_stage = last_ok or "pipeline_start"
    rec.last_successful_stage = last_ok
    rec.error_message = (failed_evt.detail or "").strip()[:1000] or None
    # Writer schema failure is the most diagnosable class — the
    # orchestrator persists it on session_metadata under
    # ``writer_schema_failure`` (W7/D5 iterate + W19/D1 carry).
    wsf = session_meta.get("writer_schema_failure")
    if isinstance(wsf, dict):
        rec.writer_schema_failure = {
            "schema_name": wsf.get("schema_name"),
            "field_path": wsf.get("field_path"),
            # NOTE: NEVER include raw_text_excerpt — it can carry
            # writer prose. The schema + field path is enough for
            # an operator to find the failure in code.
        }
    # Whichever LLM call errored last is a good proxy for the
    # provider-level error kind (timeouts, content-policy, etc.).
    for c in reversed(llm_calls):
        if not c.success and c.error_kind:
            rec.error_kind = c.error_kind
            break
    return rec


# ---------------------------------------------------------------------------
# Public assembler
# ---------------------------------------------------------------------------


async def assemble_trace(
    session_id: str,
    run_id: str | None = None,
) -> EngagementTrace | None:
    """Build :class:`EngagementTrace` for one session. Returns
    ``None`` when the session doesn't exist; the API maps that
    to 404."""
    sess = await _load_session_view(session_id)
    if sess is None:
        return None

    trace = EngagementTrace(
        session_id=session_id,
        firm_id=sess.get("firm_id"),
        run_id=run_id,
        status=sess.get("status"),
        pipeline_state=sess.get("pipeline_state"),
        report_mode=sess.get("report_mode"),
    )

    meta = sess.get("metadata") or {}
    events = meta.get("pipeline_trace") if isinstance(meta, dict) else None
    if isinstance(events, list) and events:
        trace.timeline = _build_timeline(events)
        # Started / ended timestamps from the timeline bookends.
        first_at = next((e.at for e in trace.timeline if e.at), None)
        last_at = next(
            (e.at for e in reversed(trace.timeline) if e.at), None,
        )
        trace.started_at = first_at
        trace.ended_at = last_at
        fdt = _parse_iso(first_at)
        ldt = _parse_iso(last_at)
        if fdt and ldt:
            trace.wall_ms = (ldt - fdt).total_seconds() * 1000.0
    else:
        trace.gaps.append("pipeline_trace_missing")

    trace.llm_calls = await _load_llm_calls(session_id)
    if not trace.llm_calls:
        trace.gaps.append("llm_calls_missing")
    trace.stage_rollups = _rollup_by_agent(trace.llm_calls)
    trace.total_cost_usd = sum(r.cost_usd for r in trace.stage_rollups)

    trace.verification = await _load_verification_summary(session_id)
    if trace.verification.assessments_total == 0:
        trace.gaps.append("verification_metrics_missing")

    trace.retrieval = await _load_retrieval_summary(session_id, meta)
    if trace.retrieval.evidence_count == 0:
        trace.gaps.append("retrieval_metrics_missing")

    trace.versions = await _load_versions(session_id)

    trace.failure = _diagnose_failure(trace.timeline, meta, trace.llm_calls)
    if not trace.failure.failed and sess.get("status") == "failed":
        # Session marked failed but the timeline didn't record an
        # explicit ``failed`` event — produce a minimal diagnostic.
        trace.failure.failed = True
        trace.failure.failed_stage = sess.get("pipeline_state") or "unknown"
        trace.failure.last_successful_stage = (
            trace.timeline[-1].stage if trace.timeline else None
        )

    return trace


# ---------------------------------------------------------------------------
# Recent traces (debugging surface)
# ---------------------------------------------------------------------------


async def recent_traces(
    *,
    status: str | None = None,
    firm_id: str | None = None,
    hours: int = 24,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Lightweight digest of recent engagements: session_id, firm,
    status, pipeline_state, started_at, updated_at, total_cost,
    failure stage (when applicable).

    Filterable by status — ``recent_traces(status='failed')`` is
    the "show me what blew up today" query. Firm-scoped: caller
    should pass ``firm_id`` when the user is a firm_admin (not a
    system admin).
    """
    where_clauses: list[str] = ["updated_at > NOW() - $1::interval"]
    params: list[Any] = [f"{int(hours)} hours"]
    if status:
        params.append(status)
        where_clauses.append(f"status = ${len(params)}")
    if firm_id:
        params.append(firm_id)
        where_clauses.append(f"firm_id = ${len(params)}::uuid")
    where = " AND ".join(where_clauses)

    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT s.id, s.firm_id, s.status, s.pipeline_state,
                       s.report_mode, s.created_at, s.updated_at, s.metadata,
                       COALESCE(
                           (SELECT SUM(cost_usd) FROM cost_ledger
                             WHERE session_id = s.id),
                           0
                       )::float AS total_cost_usd
                  FROM sessions s
                 WHERE {where}
                 ORDER BY s.updated_at DESC
                 LIMIT {int(limit)}
                """,
                *params,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("recent_traces failed: %s", e)
        return []
    out = []
    for r in rows:
        meta = r["metadata"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        events = meta.get("pipeline_trace") if isinstance(meta, dict) else None
        timeline = _build_timeline(events) if isinstance(events, list) else []
        failure = _diagnose_failure(timeline, meta or {}, [])
        out.append({
            "session_id": str(r["id"]),
            "firm_id": str(r["firm_id"]) if r["firm_id"] else None,
            "status": r["status"],
            "pipeline_state": r["pipeline_state"],
            "report_mode": r["report_mode"],
            "started_at": r["created_at"].isoformat() if r["created_at"] else None,
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "total_cost_usd": float(r["total_cost_usd"] or 0.0),
            "failed_stage": failure.failed_stage if failure.failed else None,
            "error_message": failure.error_message if failure.failed else None,
        })
    return out


__all__ = [
    "EngagementTrace",
    "FailureRecord",
    "LLMCallRow",
    "RetrievalSummary",
    "StageRollup",
    "TimelineStage",
    "VerificationSummary",
    "assemble_trace",
    "recent_traces",
]
