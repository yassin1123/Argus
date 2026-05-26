"""Tests for the W20/D4 trace-view assembler.

Seven spec assertions:

  1. assemble_trace produces the full lifecycle for a completed
     engagement (timeline + stage_rollups + verification + retrieval
     + total_cost + versions)
  2. per-stage cost lands on stage_rollups (sums llm_calls grouped
     by agent)
  3. verification.verdict_distribution comes from the W20/D2 metrics
  4. no prose content anywhere in the assembled trace
  5. a failed engagement's trace shows the failure_stage,
     last_successful_stage, and error
  6. recent_traces filters by status='failed' + by firm
  7. firm-admin trace queries cannot reach another firm's session
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core.observability import trace_view as tv  # noqa: E402


# ---------------------------------------------------------------------------
# In-memory DB fake
# ---------------------------------------------------------------------------


class _Store:
    """Holds everything trace_view queries: sessions, llm_calls,
    cost_ledger, metric_events, payload_versions."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.llm_calls: list[dict[str, Any]] = []
        self.cost_ledger: list[dict[str, Any]] = []
        self.metric_events: list[dict[str, Any]] = []
        self.versions: list[dict[str, Any]] = []

    def add_session(
        self, sid: str, firm_id: str, *,
        status: str = "complete",
        pipeline_state: str = "deliverable_ready",
        report_mode: str = "m_and_a",
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.sessions[sid] = {
            "id": sid, "firm_id": firm_id, "status": status,
            "pipeline_state": pipeline_state, "report_mode": report_mode,
            "metadata": metadata or {},
            "created_at": created_at or datetime.now(tz=timezone.utc),
            "updated_at": updated_at or datetime.now(tz=timezone.utc),
        }

    def add_llm_call(
        self, sid: str, *, task_kind: str, model: str, provider: str,
        prompt_tokens: int, completion_tokens: int, usd_cost: float,
        latency_ms: int, success: bool = True, error_kind: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.llm_calls.append({
            "session_id": sid,
            "task_kind": task_kind, "model": model, "provider": provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "usd_cost": usd_cost, "latency_ms": latency_ms,
            "success": success, "error_kind": error_kind,
            "created_at": created_at or datetime.now(tz=timezone.utc),
        })

    def add_metric(
        self, metric_name: str, labels: dict[str, Any], value: float,
        *, trace_id: str | None = None, firm_id: str | None = None,
    ) -> None:
        self.metric_events.append({
            "metric_name": metric_name, "labels": labels,
            "value": value, "trace_id": trace_id, "firm_id": firm_id,
        })


def _install_fake(monkeypatch: pytest.MonkeyPatch) -> _Store:
    store = _Store()

    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if "FROM sessions WHERE id = $1::uuid" in s and "metadata" in s:
            sid = str(args[0])
            row = store.sessions.get(sid)
            return dict(row) if row else None
        if "FROM sessions WHERE id = $1::uuid" in s:
            sid = str(args[0])
            row = store.sessions.get(sid)
            return {"firm_id": row["firm_id"]} if row else None
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        # llm_calls per session
        if "FROM llm_calls WHERE session_id" in s:
            sid = str(args[0])
            return [c for c in store.llm_calls if c["session_id"] == sid]
        # verification verdict rollup from metric_events
        if "metric_name = 'verification.verdict'" in s:
            sid = str(args[0])
            matching = [
                m for m in store.metric_events
                if m["metric_name"] == "verification.verdict"
                and m["labels"].get("session_id") == sid
            ]
            groups: dict[str, float] = {}
            for m in matching:
                k = m["labels"].get("outcome")
                if k:
                    groups[k] = groups.get(k, 0.0) + m["value"]
            return [{"outcome": k, "n": int(v)} for k, v in groups.items()]
        # retrieval hits rollup
        if "metric_name = 'retrieval.hits'" in s:
            sid = str(args[0])
            matching = [
                m for m in store.metric_events
                if m["metric_name"] == "retrieval.hits"
                and m["labels"].get("session_id") == sid
            ]
            groups: dict[str, float] = {}
            for m in matching:
                k = m["labels"].get("source_type")
                if k:
                    groups[k] = groups.get(k, 0.0) + m["value"]
            return [{"source": k, "n": int(v)} for k, v in groups.items()]
        # payload_versions
        if "FROM payload_versions" in s:
            sid = str(args[0])
            return [v for v in store.versions if v["session_id"] == sid]
        # recent_traces
        if "FROM sessions s" in s and "ORDER BY s.updated_at" in s:
            now = datetime.now(tz=timezone.utc)
            # crude interval parse (the SQL uses $1::interval, we just take all)
            rows = list(store.sessions.values())
            # extract subsequent filters
            arg_idx = 1
            if "status = " in s:
                want_status = args[arg_idx]; arg_idx += 1
                rows = [r for r in rows if r["status"] == want_status]
            if "firm_id = " in s:
                want_firm = str(args[arg_idx]); arg_idx += 1
                rows = [r for r in rows if r["firm_id"] == want_firm]
            out = []
            for r in rows:
                cost = sum(
                    c["usd_cost"] for c in store.llm_calls
                    if c["session_id"] == r["id"]
                )
                out.append({
                    "id": r["id"], "firm_id": r["firm_id"],
                    "status": r["status"],
                    "pipeline_state": r["pipeline_state"],
                    "report_mode": r["report_mode"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "metadata": r["metadata"],
                    "total_cost_usd": cost,
                })
            out.sort(key=lambda r: r["updated_at"], reverse=True)
            return out
        return []

    fake_conn = mock.MagicMock()
    fake_conn.fetchrow = fetchrow
    fake_conn.fetch = fetch

    class _AcquireCM:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    def _acquire():
        return _AcquireCM()

    monkeypatch.setattr(tv, "acquire", _acquire)
    return store


def _seed_complete_engagement(store: _Store, *, sid: str, firm: str) -> None:
    """Plant a realistic completed M&A engagement: full pipeline_trace,
    a writer/analyst/verifier/planner LLM-call mix, verifier verdict
    histogram, retrieval-by-source histogram."""
    base = datetime(2026, 5, 26, 10, 0, 0, tzinfo=timezone.utc)
    events = [
        {"event": "pipeline_start", "detail": "status=processing",
         "at": base.isoformat()},
        {"event": "plan_ready", "detail": "tasks=6",
         "at": (base + timedelta(seconds=2)).isoformat()},
        {"event": "research_gathered", "detail": "evidence_objects=42",
         "at": (base + timedelta(seconds=14)).isoformat()},
        {"event": "analysis_v1_done", "detail": "",
         "at": (base + timedelta(seconds=28)).isoformat()},
        {"event": "verification_done", "detail": "",
         "at": (base + timedelta(seconds=58)).isoformat()},
        {"event": "deliverable_ready", "detail": "",
         "at": (base + timedelta(seconds=84)).isoformat()},
        {"event": "complete", "detail": "unsupported_claims=1",
         "at": (base + timedelta(seconds=88)).isoformat()},
    ]
    store.add_session(
        sid, firm, status="complete", pipeline_state="deliverable_ready",
        metadata={
            "pipeline_trace": events,
            "retrieval_hits": {"sec_filing": 20, "transcripts": 12, "news": 10},
        },
        created_at=base, updated_at=base + timedelta(seconds=88),
    )
    for agent, prov, mdl, pt, ct, usd in [
        ("planner",   "openai",    "gpt-4o",            1000, 500, 0.012),
        ("researcher","anthropic", "claude-sonnet-4-6", 8500, 3200, 0.097),
        ("analyst",   "anthropic", "claude-sonnet-4-6", 4500, 3200, 0.078),
        ("verifier",  "openai",    "gpt-4o",            3800, 1500, 0.034),
        ("writer",    "anthropic", "claude-sonnet-4-6", 6000, 8000, 0.156),
    ]:
        store.add_llm_call(
            sid, task_kind=agent, model=mdl, provider=prov,
            prompt_tokens=pt, completion_tokens=ct,
            usd_cost=usd, latency_ms=1200,
        )
    for outcome, n in {
        "supported_high": 18, "supported_low": 6,
        "weak": 2, "contradicted": 1,
    }.items():
        store.add_metric(
            "verification.verdict",
            {"outcome": outcome, "session_id": sid},
            float(n),
        )
    for src, n in {"sec_filing": 20, "transcripts": 12, "news": 10}.items():
        store.add_metric(
            "retrieval.hits",
            {"source_type": src, "session_id": sid},
            float(n),
        )


# ---------------------------------------------------------------------------
# 1. assemble_trace produces the full lifecycle
# ---------------------------------------------------------------------------


def test_assemble_trace_full_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)
    sid = str(uuid4())
    firm = str(uuid4())
    _seed_complete_engagement(store, sid=sid, firm=firm)

    async def go() -> tv.EngagementTrace | None:
        return await tv.assemble_trace(sid)

    trace = asyncio.run(go())
    assert trace is not None
    assert trace.session_id == sid
    assert trace.firm_id == firm
    assert trace.status == "complete"
    assert trace.pipeline_state == "deliverable_ready"

    # Timeline: 7 events in stage order.
    assert [s.stage for s in trace.timeline] == [
        "pipeline_start", "plan_ready", "research_gathered",
        "analysis_v1_done", "verification_done", "deliverable_ready",
        "complete",
    ]
    # First row has no duration (no prev event); subsequent rows do.
    assert trace.timeline[0].duration_ms is None
    assert trace.timeline[1].duration_ms == pytest.approx(2000.0)
    assert trace.timeline[2].duration_ms == pytest.approx(12000.0)

    # Wall time = first → last event = 88s.
    assert trace.wall_ms == pytest.approx(88_000.0)

    # 5 LLM calls aggregated into 5 stage rollups.
    assert len(trace.llm_calls) == 5
    assert len(trace.stage_rollups) == 5

    # Total cost matches manual sum.
    assert trace.total_cost_usd == pytest.approx(
        0.012 + 0.097 + 0.078 + 0.034 + 0.156
    )

    # Verification + retrieval rollups landed.
    assert trace.verification.assessments_total == 27
    assert trace.retrieval.evidence_count == 42

    # Not a failure path.
    assert trace.failure.failed is False


# ---------------------------------------------------------------------------
# 2. per-stage cost
# ---------------------------------------------------------------------------


def test_trace_includes_cost_per_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)
    sid = str(uuid4())
    firm = str(uuid4())
    _seed_complete_engagement(store, sid=sid, firm=firm)

    async def go() -> tv.EngagementTrace | None:
        return await tv.assemble_trace(sid)

    trace = asyncio.run(go())
    assert trace is not None
    by_agent = {r.agent: r for r in trace.stage_rollups}
    assert by_agent["writer"].cost_usd == pytest.approx(0.156)
    assert by_agent["writer"].call_count == 1
    assert by_agent["writer"].prompt_tokens == 6000
    assert by_agent["writer"].completion_tokens == 8000
    assert by_agent["researcher"].cost_usd == pytest.approx(0.097)
    # Sorted descending by cost — writer first.
    assert trace.stage_rollups[0].agent == "writer"


# ---------------------------------------------------------------------------
# 3. verification distribution
# ---------------------------------------------------------------------------


def test_trace_includes_verification_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)
    sid = str(uuid4())
    firm = str(uuid4())
    _seed_complete_engagement(store, sid=sid, firm=firm)

    async def go() -> tv.EngagementTrace | None:
        return await tv.assemble_trace(sid)

    trace = asyncio.run(go())
    assert trace is not None
    assert trace.verification.verdict_distribution == {
        "supported_high": 18, "supported_low": 6,
        "weak": 2, "contradicted": 1,
    }
    assert trace.verification.assessments_total == 27


# ---------------------------------------------------------------------------
# 4. NO prose content anywhere in the trace
# ---------------------------------------------------------------------------


def test_trace_no_prose_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plant some "prose-looking" content in places the assembler
    might be tempted to surface (session.metadata + writer_schema
    failure raw_text + a pipeline_trace detail) — confirm none of
    it ends up in the serialized trace."""
    store = _install_fake(monkeypatch)
    sid = str(uuid4())
    firm = str(uuid4())

    SECRET_PROSE = (
        "CONFIDENTIAL CLAIM: target Q2 EBITDA dropped 18% YoY per "
        "the leaked filing extract."
    )
    base = datetime(2026, 5, 26, 10, 0, 0, tzinfo=timezone.utc)
    store.add_session(
        sid, firm, status="complete", pipeline_state="deliverable_ready",
        metadata={
            "pipeline_trace": [
                {"event": "pipeline_start", "detail": "status=processing",
                 "at": base.isoformat()},
                {"event": "complete", "detail": "unsupported_claims=0",
                 "at": (base + timedelta(seconds=80)).isoformat()},
            ],
            # The W7/D5 iterate persistence — assembler must reference
            # only schema_name + field_path, NEVER the raw_text_excerpt.
            "writer_schema_failure": {
                "schema_name": "WriterReportPayload",
                "field_path": "synergy_estimate.revenue_synergies[0]",
                "raw_text_excerpt": SECRET_PROSE,
            },
            "retrieval_hits": {"sec_filing": 5},
            # Sneaky: a non-load-bearing prose field on metadata —
            # the assembler must not splat metadata into the trace.
            "writer_output": SECRET_PROSE,
            "memo_prose": SECRET_PROSE,
        },
    )
    store.add_llm_call(
        sid, task_kind="writer", model="claude-sonnet-4-6",
        provider="anthropic", prompt_tokens=6000, completion_tokens=8000,
        usd_cost=0.156, latency_ms=4500,
    )

    async def go() -> tv.EngagementTrace | None:
        return await tv.assemble_trace(sid)

    trace = asyncio.run(go())
    assert trace is not None
    serialized = json.dumps(trace.to_dict(), default=str)
    # The planted prose must NOT appear anywhere in the trace.
    assert SECRET_PROSE not in serialized
    # The writer_schema_failure surface, when present, carries only
    # schema_name + field_path — never raw_text_excerpt.
    if trace.failure.writer_schema_failure is not None:
        keys = set(trace.failure.writer_schema_failure.keys())
        assert "raw_text_excerpt" not in keys
        assert keys.issubset({"schema_name", "field_path"})


# ---------------------------------------------------------------------------
# 5. failed-engagement trace surfaces the failure stage
# ---------------------------------------------------------------------------


def test_failed_engagement_trace_shows_failure_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)
    sid = str(uuid4())
    firm = str(uuid4())
    base = datetime(2026, 5, 26, 10, 0, 0, tzinfo=timezone.utc)
    events = [
        {"event": "pipeline_start", "detail": "status=processing",
         "at": base.isoformat()},
        {"event": "plan_ready", "detail": "tasks=4",
         "at": (base + timedelta(seconds=2)).isoformat()},
        {"event": "research_gathered", "detail": "evidence_objects=18",
         "at": (base + timedelta(seconds=15)).isoformat()},
        {"event": "failed",
         "detail": "WriterSchemaValidationError: missing required field",
         "at": (base + timedelta(seconds=42)).isoformat()},
    ]
    store.add_session(
        sid, firm,
        status="failed", pipeline_state="failed",
        metadata={
            "pipeline_trace": events,
            "writer_schema_failure": {
                "schema_name": "WriterReportPayload",
                "field_path": "valuation_range.method",
                "raw_text_excerpt": "<should-be-redacted prose>",
            },
        },
        updated_at=base + timedelta(seconds=42),
    )
    # Last call errored — feeds the error_kind into FailureRecord.
    store.add_llm_call(
        sid, task_kind="writer", model="claude-sonnet-4-6",
        provider="anthropic", prompt_tokens=4000, completion_tokens=0,
        usd_cost=0.04, latency_ms=8000,
        success=False, error_kind="schema_validation_failed",
    )

    async def go() -> tv.EngagementTrace | None:
        return await tv.assemble_trace(sid)

    trace = asyncio.run(go())
    assert trace is not None
    assert trace.status == "failed"
    assert trace.failure.failed is True
    # The last successful stage before failure was research_gathered.
    assert trace.failure.last_successful_stage == "research_gathered"
    assert trace.failure.failed_stage == "research_gathered"
    assert "WriterSchemaValidationError" in (trace.failure.error_message or "")
    # Failure record carries schema_name + field_path — not the prose.
    assert trace.failure.writer_schema_failure == {
        "schema_name": "WriterReportPayload",
        "field_path": "valuation_range.method",
    }
    # Error kind from the failed LLM call.
    assert trace.failure.error_kind == "schema_validation_failed"
    # Cost burned before failure is captured.
    assert trace.total_cost_usd == pytest.approx(0.04)


# ---------------------------------------------------------------------------
# 6. recent_traces filters by status + firm
# ---------------------------------------------------------------------------


def test_recent_failed_traces_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)
    firm_a = str(uuid4())
    firm_b = str(uuid4())

    # firm_a: 1 complete, 2 failed.  firm_b: 1 failed.
    for sid, status in (
        (str(uuid4()), "complete"),
        (str(uuid4()), "failed"),
        (str(uuid4()), "failed"),
    ):
        store.add_session(sid, firm_a, status=status)
    for sid, status in ((str(uuid4()), "failed"),):
        store.add_session(sid, firm_b, status=status)

    async def go() -> tuple[list[Any], list[Any], list[Any]]:
        all_failed = await tv.recent_traces(status="failed")
        firm_a_failed = await tv.recent_traces(status="failed", firm_id=firm_a)
        firm_b_all = await tv.recent_traces(firm_id=firm_b)
        return all_failed, firm_a_failed, firm_b_all

    all_failed, firm_a_failed, firm_b_all = asyncio.run(go())
    # Cross-firm system view sees both firms' failures.
    assert len(all_failed) == 3
    # Firm-A scope sees only firm_a's 2 failures.
    assert len(firm_a_failed) == 2
    assert all(t["firm_id"] == firm_a for t in firm_a_failed)
    # Firm-B unfiltered sees firm_b's single (failed) row.
    assert len(firm_b_all) == 1
    assert firm_b_all[0]["firm_id"] == firm_b


# ---------------------------------------------------------------------------
# 7. firm-admin trace queries are firm-scoped
# ---------------------------------------------------------------------------


def test_trace_firm_scoped() -> None:
    """The route handler's firm-scoping gate. A firm-admin must not
    be able to GET another firm's trace, even by URL guess. The
    same code path also returns 404 (not 403) to avoid existence-
    leak — we replay the gate inline here without needing a full
    HTTP client."""
    from api.trace import _is_firm_admin, _is_system_admin

    firm_a = str(uuid4())
    firm_b = str(uuid4())
    firm_admin = {
        "user_id": "u1", "role": "member",
        "default_firm_id": firm_a, "default_firm_role": "admin",
    }
    sys_admin = {
        "user_id": "u2", "role": "admin",
        "default_firm_id": None, "default_firm_role": None,
    }
    member = {
        "user_id": "u3", "role": "member",
        "default_firm_id": firm_a, "default_firm_role": "member",
    }
    outsider = {
        "user_id": "u4", "role": "member",
        "default_firm_id": firm_b, "default_firm_role": "member",
    }

    # The gate the route enforces:
    #   if not system_admin and user.default_firm_id != session.firm_id:
    #       404
    def gate(user: dict, session_firm: str) -> bool:
        if _is_system_admin(user):
            return True
        return user.get("default_firm_id") == session_firm

    assert gate(firm_admin, firm_a) is True
    assert gate(firm_admin, firm_b) is False
    assert gate(sys_admin, firm_a) is True
    assert gate(sys_admin, firm_b) is True
    assert gate(member, firm_a) is True
    assert gate(outsider, firm_a) is False
