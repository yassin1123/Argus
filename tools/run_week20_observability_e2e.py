"""Phase 5 / Week 20 / Day 5 — observability end-to-end demo.

Runs a realistic multi-engagement workload through the W20
observability stack (D1 logging + D2 metrics + D3 cost ledger +
D4 trace assembly + D5 dashboard) and asserts every promise the
spec made:

  1. every engagement produced a complete trace
  2. cost ledger sums match per-engagement reported costs
  3. metrics reflect the runs (engagement + LLM-call counts +
     verification distribution)
  4. the failed engagement has a diagnosable trace (failure
     stage + reason + cost-before-failure)
  5. no prose content leaked into any log, metric, or trace
  6. firm scoping holds (firm-B's data does not appear in
     firm-A's dashboard queries)

Cost discipline (per the W20/D5 hard rule "Cap it; cache where
the demo allows"): this runner does **NOT** call any LLM. It
seeds the same in-memory fake DB the per-day tests use with
realistic engagement footprints (token counts + cost values
derived from the eval-run history) and exercises the real
assemble_trace / engagement_cost / dashboard code paths against
that fake. Total real-money spend: $0.00. The shape of the
assertions matches what a real engagement workload would
produce.

Usage::

    python tools/run_week20_observability_e2e.py
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "backend"))
sys.path.insert(0, str(_REPO))

# --- W20 modules under test ---
from core.observability import cost as cost_mod
from core.observability import cost_rollups as roll_mod
from core.observability import logging as obs_logging
from core.observability import metrics as metrics_mod
from core.observability import trace_view as tv
from core.observability.logging import (
    REDACTED_VALUE,
    configure_event_logging,
    emit_event,
    reset_configuration_for_tests,
)
from core.observability.trace import bind_trace_context, new_run_id, new_trace_id


# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------


OUT_DIR = _REPO / "backend" / "eval_runs" / "week20_observability"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_PATH = OUT_DIR / "summary.json"


# ---------------------------------------------------------------------------
# In-memory DB fake (shared across cost / cost_rollups / trace_view)
# ---------------------------------------------------------------------------


@dataclass
class _Store:
    sessions: dict[str, dict[str, Any]] = field(default_factory=dict)
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    cost_rows: list[dict[str, Any]] = field(default_factory=list)
    metric_rows: list[dict[str, Any]] = field(default_factory=list)


_STORE = _Store()


# Async DB stubs ------------------------------------------------------------


async def _execute(sql: str, *args: Any) -> str:
    s = " ".join(sql.split())
    if "INSERT INTO metric_events" in s:
        _STORE.metric_rows.append({
            "metric_name": args[0],
            "labels": json.loads(args[1]) if isinstance(args[1], str) else (args[1] or {}),
            "value": float(args[2]),
            "trace_id": str(args[3]) if args[3] else None,
            "firm_id": str(args[4]) if args[4] else None,
            "recorded_at": datetime.now(tz=timezone.utc),
        })
        return "INSERT 0 1"
    if "INSERT INTO cost_ledger" in s:
        _STORE.cost_rows.append({
            "trace_id": str(args[0]) if args[0] else None,
            "session_id": str(args[1]) if args[1] else None,
            "firm_id": str(args[2]),
            "agent": args[3], "provider": args[4], "model": args[5],
            "prompt_tokens": int(args[6]),
            "completion_tokens": int(args[7]),
            "cost_usd": float(args[8]),
            "recorded_at": datetime.now(tz=timezone.utc),
        })
        return "INSERT 0 1"
    return "OK"


async def _fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
    s = " ".join(sql.split())
    if "FROM sessions WHERE id = $1::uuid" in s and "metadata" in s:
        return _STORE.sessions.get(str(args[0]))
    if "FROM sessions WHERE id = $1::uuid" in s:
        sess = _STORE.sessions.get(str(args[0]))
        return {"firm_id": sess["firm_id"]} if sess else None
    if "FROM cost_ledger WHERE session_id" in s and "SUM(cost_usd)" in s and "call_count" in s:
        sid = str(args[0])
        matching = [r for r in _STORE.cost_rows if r["session_id"] == sid]
        return {
            "total": float(sum(r["cost_usd"] for r in matching)),
            "call_count": len(matching),
            "pt": int(sum(r["prompt_tokens"] for r in matching)),
            "ct": int(sum(r["completion_tokens"] for r in matching)),
        }
    if "FROM cost_ledger WHERE session_id" in s:
        sid = str(args[0])
        matching = [r for r in _STORE.cost_rows if r["session_id"] == sid]
        return {"total": float(sum(r["cost_usd"] for r in matching))}
    if "COUNT(DISTINCT session_id)" in s:
        firm_id = str(args[0])
        matching = [r for r in _STORE.cost_rows if r["firm_id"] == firm_id]
        arg_iter = iter(args[1:])
        if "recorded_at >= " in s:
            f = next(arg_iter)
            matching = [r for r in matching if r["recorded_at"] >= f]
        if "recorded_at < " in s:
            t = next(arg_iter)
            matching = [r for r in matching if r["recorded_at"] < t]
        return {
            "total": float(sum(r["cost_usd"] for r in matching)),
            "call_count": len(matching),
            "engagement_count": len({r["session_id"] for r in matching}),
        }
    return None


def _match_window(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    for k, v in filters.items():
        if k == "from_ts" and row["recorded_at"] < v: return False
        if k == "to_ts" and row["recorded_at"] >= v: return False
        if k == "metric_name" and row["metric_name"] != v: return False
        if k == "firm_id" and row["firm_id"] != v: return False
    return True


async def _fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
    s = " ".join(sql.split())
    # ---- metric_events queries (metrics_mod.query_window + render_prometheus) ----
    if "SELECT DISTINCT metric_name" in s:
        firm = args[0] if args else None
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for r in _STORE.metric_rows:
            if firm is not None and r["firm_id"] != str(firm):
                continue
            if r["metric_name"] not in seen:
                seen.add(r["metric_name"])
                out.append({"metric_name": r["metric_name"]})
        out.sort(key=lambda r: r["metric_name"])
        return out
    if "FROM metric_events" in s and "metric_name = $1" in s:
        metric_name = args[0]
        filters: dict[str, Any] = {"metric_name": metric_name}
        arg_iter = iter(args[1:])
        if "recorded_at >= " in s:
            filters["from_ts"] = next(arg_iter)
        if "recorded_at < " in s:
            filters["to_ts"] = next(arg_iter)
        if "firm_id = " in s:
            filters["firm_id"] = str(next(arg_iter))
        group_field: str | None = None
        if "GROUP BY" in s and "labels ->>" in s:
            group_field = str(next(arg_iter))
        matching = [r for r in _STORE.metric_rows if _match_window(r, filters)]
        if group_field is None:
            if not matching:
                return [{"grp": None, "count": 0, "sum": 0.0, "avg": 0.0, "min": 0.0, "max": 0.0}]
            vals = [r["value"] for r in matching]
            return [{
                "grp": None, "count": len(vals), "sum": sum(vals),
                "avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals),
            }]
        groups: dict[Any, list[float]] = {}
        for r in matching:
            g = r["labels"].get(group_field) if isinstance(r["labels"], dict) else None
            groups.setdefault(g, []).append(r["value"])
        out = []
        for g, vals in groups.items():
            out.append({
                "grp": g, "count": len(vals), "sum": sum(vals),
                "avg": sum(vals) / len(vals), "min": min(vals), "max": max(vals),
            })
        out.sort(key=lambda r: r["count"], reverse=True)
        return out
    # ---- verification verdict from metric_events for trace_view ----
    if "metric_name = 'verification.verdict'" in s:
        sid = str(args[0])
        matching = [
            m for m in _STORE.metric_rows
            if m["metric_name"] == "verification.verdict"
            and m["labels"].get("session_id") == sid
        ]
        groups: dict[str, float] = {}
        for m in matching:
            k = m["labels"].get("outcome")
            if k:
                groups[k] = groups.get(k, 0.0) + m["value"]
        return [{"outcome": k, "n": int(v)} for k, v in groups.items()]
    if "metric_name = 'retrieval.hits'" in s:
        sid = str(args[0])
        matching = [
            m for m in _STORE.metric_rows
            if m["metric_name"] == "retrieval.hits"
            and m["labels"].get("session_id") == sid
        ]
        groups: dict[str, float] = {}
        for m in matching:
            k = m["labels"].get("source_type")
            if k:
                groups[k] = groups.get(k, 0.0) + m["value"]
        return [{"source": k, "n": int(v)} for k, v in groups.items()]
    # ---- llm_calls per session ----
    if "FROM llm_calls WHERE session_id" in s:
        sid = str(args[0])
        return [c for c in _STORE.llm_calls if c["session_id"] == sid]
    # ---- payload_versions (empty for this e2e) ----
    if "FROM payload_versions" in s:
        return []
    # ---- recent_traces ----
    if "FROM sessions s" in s and "ORDER BY s.updated_at" in s:
        rows = list(_STORE.sessions.values())
        arg_idx = 1  # skip the interval arg
        if "status = " in s:
            want_status = args[arg_idx]; arg_idx += 1
            rows = [r for r in rows if r["status"] == want_status]
        if "firm_id = " in s:
            want_firm = str(args[arg_idx]); arg_idx += 1
            rows = [r for r in rows if r["firm_id"] == want_firm]
        out = []
        for r in rows:
            cost = sum(
                c["usd_cost"] for c in _STORE.llm_calls if c["session_id"] == r["id"]
            )
            out.append({
                "id": r["id"], "firm_id": r["firm_id"],
                "status": r["status"], "pipeline_state": r["pipeline_state"],
                "report_mode": r["report_mode"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
                "metadata": r["metadata"], "total_cost_usd": cost,
            })
        out.sort(key=lambda r: r["updated_at"], reverse=True)
        return out
    # ---- cost ledger groupings ----
    if "FROM cost_ledger WHERE session_id" in s and "GROUP BY" in s:
        sid = str(args[0])
        matching = [r for r in _STORE.cost_rows if r["session_id"] == sid]
        field_ = "agent" if "GROUP BY agent" in s else "model"
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in matching:
            groups.setdefault(r[field_], []).append(r)
        out = []
        for label, rs in groups.items():
            out.append({
                "label": label, "count": len(rs),
                "cost_usd": float(sum(r["cost_usd"] for r in rs)),
                "pt": int(sum(r["prompt_tokens"] for r in rs)),
                "ct": int(sum(r["completion_tokens"] for r in rs)),
            })
        out.sort(key=lambda r: r["cost_usd"], reverse=True)
        return out
    if "FROM cost_ledger WHERE firm_id" in s and "GROUP BY" in s:
        firm_id = str(args[0])
        matching = [r for r in _STORE.cost_rows if r["firm_id"] == firm_id]
        arg_iter = iter(args[1:])
        if "recorded_at >= " in s:
            f = next(arg_iter)
            matching = [r for r in matching if r["recorded_at"] >= f]
        if "recorded_at < " in s:
            t = next(arg_iter)
            matching = [r for r in matching if r["recorded_at"] < t]
        field_ = "session_id" if "GROUP BY session_id" in s else "model"
        groups = {}
        for r in matching:
            k = r[field_] or "unattributed"
            groups.setdefault(k, []).append(r)
        out = []
        for label, rs in groups.items():
            out.append({
                "label": label, "count": len(rs),
                "cost_usd": float(sum(r["cost_usd"] for r in rs)),
                "pt": int(sum(r["prompt_tokens"] for r in rs)),
                "ct": int(sum(r["completion_tokens"] for r in rs)),
            })
        out.sort(key=lambda r: r["cost_usd"], reverse=True)
        return out
    return []


class _FakeConn:
    execute = staticmethod(_execute)
    fetchrow = staticmethod(_fetchrow)
    fetch = staticmethod(_fetch)


class _AcquireCM:
    async def __aenter__(self): return _FakeConn()
    async def __aexit__(self, *a): return None


def _acquire():
    return _AcquireCM()


def _install_db_fake() -> None:
    cost_mod.acquire = _acquire           # type: ignore[assignment]
    roll_mod.acquire = _acquire           # type: ignore[assignment]
    metrics_mod.acquire = _acquire        # type: ignore[assignment]
    tv.acquire = _acquire                 # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Engagement footprints
# ---------------------------------------------------------------------------


@dataclass
class EngagementSpec:
    sid: str
    firm_id: str
    title: str
    mode: str
    failed: bool = False
    failure_detail: str | None = None
    failure_stage: str | None = None


# Per-stage cost profile by mode. Derived from the eval-run summaries
# the team committed in W7/W8 (typical M&A engagement ≈ $0.40, growth
# ≈ $0.30). Token mix is realistic for the writer-heavy structured-
# output path.
_OK_FOOTPRINT: list[tuple[str, str, str, int, int, float]] = [
    # (agent, provider, model, prompt_tokens, completion_tokens, usd)
    ("planner",   "openai",    "gpt-4o",            1100,  500, 0.0125),
    ("researcher","anthropic", "claude-sonnet-4-6", 8500, 3200, 0.097),
    ("analyst",   "anthropic", "claude-sonnet-4-6", 4500, 3200, 0.078),
    ("critic",    "anthropic", "claude-sonnet-4-6", 3000, 1200, 0.041),
    ("verifier",  "openai",    "gpt-4o",            3800, 1500, 0.034),
    ("verifier",  "openai",    "gpt-4o",            3500, 1400, 0.032),
    ("writer",    "anthropic", "claude-sonnet-4-6", 6000, 8000, 0.156),
]

# Verifier verdict mix per engagement — realistic supported-heavy
# distribution with a couple of weak / contradicted to feed the
# Week 21 quality signal.
_OK_VERDICTS = {
    "supported_high": 18, "supported_low": 6,
    "weak": 2, "contradicted": 1,
}

# Retrieval mix per engagement.
_OK_RETRIEVAL = {"sec_filing": 20, "transcripts": 12, "news": 10}


async def _run_one_engagement(spec: EngagementSpec) -> dict[str, Any]:
    """Drive a single engagement's worth of W20 events: pipeline
    structured logs, metric writes, cost-ledger writes, plus the
    sessions row + llm_calls that trace_view reads."""
    trace_id = new_trace_id()
    run_id = new_run_id()
    base = datetime.now(tz=timezone.utc)

    # Stage timeline — landed into sessions.metadata.pipeline_trace.
    if not spec.failed:
        events = [
            {"event": "pipeline_start", "detail": "status=processing",
             "at": base.isoformat()},
            {"event": "plan_ready", "detail": "tasks=6",
             "at": (base + timedelta(seconds=2)).isoformat()},
            {"event": "research_gathered",
             "detail": f"evidence_objects={sum(_OK_RETRIEVAL.values())}",
             "at": (base + timedelta(seconds=14)).isoformat()},
            {"event": "analysis_v1_done", "detail": "",
             "at": (base + timedelta(seconds=28)).isoformat()},
            {"event": "verification_done", "detail": "",
             "at": (base + timedelta(seconds=58)).isoformat()},
            {"event": "deliverable_ready", "detail": "",
             "at": (base + timedelta(seconds=84)).isoformat()},
            {"event": "complete",
             "detail": f"unsupported_claims={_OK_VERDICTS['contradicted']}",
             "at": (base + timedelta(seconds=88)).isoformat()},
        ]
        status = "complete"
        pipeline_state = "deliverable_ready"
    else:
        events = [
            {"event": "pipeline_start", "detail": "status=processing",
             "at": base.isoformat()},
            {"event": "plan_ready", "detail": "tasks=3",
             "at": (base + timedelta(seconds=2)).isoformat()},
            {"event": "research_gathered", "detail": "evidence_objects=12",
             "at": (base + timedelta(seconds=18)).isoformat()},
            {"event": "failed",
             "detail": spec.failure_detail or "WriterSchemaValidationError: missing required field",
             "at": (base + timedelta(seconds=42)).isoformat()},
        ]
        status = "failed"
        pipeline_state = "failed"

    # Plant a realistic-but-redactable secret on metadata to prove
    # the no-prose-leak rule on the writer_schema_failure path.
    metadata: dict[str, Any] = {"pipeline_trace": events}
    if spec.failed:
        metadata["writer_schema_failure"] = {
            "schema_name": "WriterReportPayload",
            "field_path": "valuation_range.method",
            "raw_text_excerpt": SECRET_PROSE,
        }

    _STORE.sessions[spec.sid] = {
        "id": spec.sid, "firm_id": spec.firm_id,
        "status": status, "pipeline_state": pipeline_state,
        "report_mode": spec.mode, "metadata": metadata,
        "created_at": base,
        "updated_at": base + timedelta(seconds=88 if not spec.failed else 42),
    }

    # Structured events + metrics + cost ledger under the run-scoped
    # trace context. This mirrors what the orchestrator would emit
    # in a real engagement.
    with bind_trace_context(
        trace_id=trace_id, run_id=run_id,
        session_id=spec.sid, firm_id=spec.firm_id,
    ):
        emit_event("pipeline.start", report_mode=spec.mode)
        await metrics_mod.increment(
            "engagement.started",
            {"firm_id": spec.firm_id, "mode": spec.mode},
        )

        footprint = _OK_FOOTPRINT if not spec.failed else _OK_FOOTPRINT[:3]
        engagement_cost_total = 0.0
        for agent, prov, mdl, pt, ct, usd in footprint:
            # llm_calls row
            _STORE.llm_calls.append({
                "session_id": spec.sid,
                "task_kind": agent, "model": mdl, "provider": prov,
                "prompt_tokens": pt, "completion_tokens": ct,
                "usd_cost": usd, "latency_ms": 1200,
                "success": True, "error_kind": None,
                "created_at": base + timedelta(milliseconds=10),
            })
            # cost ledger (via real record_cost)
            await cost_mod.record_cost(
                trace_id=trace_id, session_id=spec.sid, firm_id=spec.firm_id,
                agent=agent, provider=prov, model=mdl,
                prompt_tokens=pt, completion_tokens=ct, cost_usd=usd,
            )
            await metrics_mod.increment(
                "llm.call",
                {"provider": prov, "model": mdl, "agent": agent,
                 "firm_id": spec.firm_id},
            )
            engagement_cost_total += usd

        if spec.failed:
            # Add one failed LLM call so the trace's error_kind populates.
            _STORE.llm_calls.append({
                "session_id": spec.sid,
                "task_kind": "writer", "model": "claude-sonnet-4-6",
                "provider": "anthropic",
                "prompt_tokens": 4000, "completion_tokens": 0,
                "usd_cost": 0.04, "latency_ms": 8000,
                "success": False, "error_kind": "schema_validation_failed",
                "created_at": base + timedelta(seconds=40),
            })
            await cost_mod.record_cost(
                trace_id=trace_id, session_id=spec.sid, firm_id=spec.firm_id,
                agent="writer", provider="anthropic",
                model="claude-sonnet-4-6",
                prompt_tokens=4000, completion_tokens=0, cost_usd=0.04,
            )
            engagement_cost_total += 0.04
            await metrics_mod.increment(
                "engagement.failed",
                {"firm_id": spec.firm_id, "mode": spec.mode,
                 "error_type": "WriterSchemaValidationError"},
            )
            emit_event(
                "pipeline.failed", level=logging.ERROR,
                duration_ms=42000.0,
                error="WriterSchemaValidationError: missing required field",
            )
        else:
            # Verifier verdict histogram → metrics
            for outcome, n in _OK_VERDICTS.items():
                await metrics_mod.increment(
                    "verification.verdict",
                    {"outcome": outcome, "session_id": spec.sid,
                     "mode": spec.mode, "firm_id": spec.firm_id},
                    value=n,
                )
            # Retrieval hits
            for src, n in _OK_RETRIEVAL.items():
                await metrics_mod.increment(
                    "retrieval.hits",
                    {"source_type": src, "session_id": spec.sid,
                     "mode": spec.mode, "firm_id": spec.firm_id},
                    value=n,
                )
            await metrics_mod.increment(
                "artifact.generated",
                {"artifact_type": "memo", "format": "payload",
                 "outcome": "ok", "mode": spec.mode,
                 "firm_id": spec.firm_id},
            )
            await metrics_mod.increment(
                "engagement.completed",
                {"firm_id": spec.firm_id, "mode": spec.mode, "outcome": "ok"},
            )
            # Also a planted secret prose attempt on a log line —
            # the W20/D1 redact rule must strip it before serialization.
            emit_event(
                "writer.complete", duration_ms=5300.0,
                report_mode=spec.mode, payload_bytes=14821,
                # Banned field names; redacted on the way out.
                writer_output=SECRET_PROSE,
                memo_prose=SECRET_PROSE,
            )

    return {
        "session_id": spec.sid, "firm_id": spec.firm_id,
        "mode": spec.mode, "status": status,
        "engagement_cost_total": engagement_cost_total,
    }


# A realistic-looking but planted secret. Used to audit every
# observability surface (log, metric, trace) for leaks.
SECRET_PROSE = (
    "CONFIDENTIAL: target Q2 EBITDA dropped 18% YoY per the leaked "
    "filing extract — internal use only, do not surface in logs."
)


# ---------------------------------------------------------------------------
# Main run + assertions
# ---------------------------------------------------------------------------


async def main() -> int:
    # 1) Capture every structured log line so we can audit it for prose.
    reset_configuration_for_tests()
    log_buf = io.StringIO()
    configure_event_logging(stream=log_buf)
    _install_db_fake()

    firm_a = str(uuid4())
    firm_b = str(uuid4())

    engagements: list[EngagementSpec] = [
        EngagementSpec(sid=str(uuid4()), firm_id=firm_a,
                       title="Kestrel Logistics M&A", mode="m_and_a"),
        EngagementSpec(sid=str(uuid4()), firm_id=firm_a,
                       title="Aurora Retail Growth", mode="growth_strategy"),
        EngagementSpec(sid=str(uuid4()), firm_id=firm_a,
                       title="Northwind Acquisitions M&A", mode="m_and_a"),
        # firm_b — used to verify firm-scoping leak prevention
        EngagementSpec(sid=str(uuid4()), firm_id=firm_b,
                       title="OtherFirm Engagement", mode="m_and_a"),
        # Forced failure to verify failure diagnosis
        EngagementSpec(sid=str(uuid4()), firm_id=firm_a,
                       title="Halo Diligence (FAILED)", mode="m_and_a",
                       failed=True,
                       failure_detail="WriterSchemaValidationError: missing required field valuation_range.method",
                       failure_stage="research_gathered"),
    ]

    summaries: list[dict[str, Any]] = []
    for spec in engagements:
        summaries.append(await _run_one_engagement(spec))

    print(f"--- ran {len(engagements)} engagements ---")
    for s in summaries:
        print(f"  {s['session_id'][:8]}...  {s['mode']:18s} "
              f"{s['status']:8s} ${s['engagement_cost_total']:.4f}")

    # =================================================================
    # ASSERTIONS
    # =================================================================
    assertions: dict[str, Any] = {}

    # --- 1) every engagement has a complete trace ---
    traces: dict[str, Any] = {}
    for spec in engagements:
        t = await tv.assemble_trace(spec.sid)
        traces[spec.sid] = t
    all_traces_present = all(t is not None for t in traces.values())
    timeline_lens = [
        len(t.timeline) if t else 0 for t in traces.values()
    ]
    assertions["all_traces_assembled"] = all_traces_present
    assertions["timeline_lens"] = timeline_lens
    assertions["min_timeline_len"] = min(timeline_lens) if timeline_lens else 0

    # --- 2) cost ledger sums match per-engagement reported costs ---
    cost_match: list[dict[str, Any]] = []
    for spec, summary in zip(engagements, summaries):
        sct = await roll_mod.session_cost_total(spec.sid)
        cost_match.append({
            "sid": spec.sid[:8] + "...",
            "ledger_total": round(sct, 6),
            "reported_total": round(summary["engagement_cost_total"], 6),
            "matches": abs(sct - summary["engagement_cost_total"]) < 1e-4,
        })
    assertions["cost_ledger_sums_match"] = all(c["matches"] for c in cost_match)
    assertions["cost_match_detail"] = cost_match

    # --- 3) metrics reflect the runs ---
    engagement_started_rows = await metrics_mod.query_window(
        "engagement.started", group_by="mode",
    )
    started_by_mode = {r["group"]: r["count"] for r in engagement_started_rows}
    llm_call_rows = await metrics_mod.query_window(
        "llm.call", group_by="provider",
    )
    llm_by_provider = {r["group"]: r["count"] for r in llm_call_rows}
    verdict_rows = await metrics_mod.query_window(
        "verification.verdict", group_by="outcome",
    )
    verdict_dist = {r["group"]: int(r["sum"]) for r in verdict_rows}
    assertions["metrics_engagements_by_mode"] = started_by_mode
    assertions["metrics_llm_calls_by_provider"] = llm_by_provider
    assertions["metrics_verdict_distribution"] = verdict_dist
    assertions["metrics_total_engagements"] = sum(started_by_mode.values())
    assertions["metrics_match_expected_engagement_count"] = (
        assertions["metrics_total_engagements"] == len(engagements)
    )

    # --- 4) failed engagement is diagnosable ---
    failed_spec = next(e for e in engagements if e.failed)
    failed_trace = traces[failed_spec.sid]
    failure_diagnosable = (
        failed_trace is not None
        and failed_trace.failure.failed is True
        and failed_trace.failure.failed_stage is not None
        and failed_trace.failure.error_message is not None
        and failed_trace.failure.error_kind is not None
        and failed_trace.failure.writer_schema_failure is not None
        and failed_trace.total_cost_usd > 0
    )
    assertions["failure_diagnosable"] = failure_diagnosable
    assertions["failed_stage"] = (
        failed_trace.failure.failed_stage if failed_trace else None
    )
    assertions["failed_error_kind"] = (
        failed_trace.failure.error_kind if failed_trace else None
    )
    assertions["failed_cost_burned"] = (
        round(failed_trace.total_cost_usd, 4) if failed_trace else 0
    )

    # --- 5) no prose content leaked ---
    log_text = log_buf.getvalue()
    metric_serialized = json.dumps(_STORE.metric_rows, default=str)
    cost_serialized = json.dumps(_STORE.cost_rows, default=str)
    trace_serialized = json.dumps(
        {sid: (t.to_dict() if t else None) for sid, t in traces.items()},
        default=str,
    )
    leak_log = SECRET_PROSE in log_text
    leak_metric = SECRET_PROSE in metric_serialized
    leak_cost = SECRET_PROSE in cost_serialized
    leak_trace = SECRET_PROSE in trace_serialized
    assertions["no_prose_in_logs"] = not leak_log
    assertions["no_prose_in_metrics"] = not leak_metric
    assertions["no_prose_in_cost_ledger"] = not leak_cost
    assertions["no_prose_in_traces"] = not leak_trace
    assertions["redaction_sentinel_in_logs"] = REDACTED_VALUE in log_text

    # --- 6) firm scoping holds ---
    firm_a_cost = await roll_mod.firm_cost(firm_a)
    firm_b_cost = await roll_mod.firm_cost(firm_b)
    firm_a_traces = await tv.recent_traces(firm_id=firm_a)
    firm_b_traces = await tv.recent_traces(firm_id=firm_b)
    firm_a_session_ids = {t["session_id"] for t in firm_a_traces}
    firm_b_session_ids = {t["session_id"] for t in firm_b_traces}
    firm_a_total = sum(
        s["engagement_cost_total"] for s in summaries
        if s["firm_id"] == firm_a
    )
    firm_b_total = sum(
        s["engagement_cost_total"] for s in summaries
        if s["firm_id"] == firm_b
    )
    assertions["firm_scoping_cost"] = {
        "firm_a_ledger": round(firm_a_cost.total_usd, 6),
        "firm_a_expected": round(firm_a_total, 6),
        "firm_b_ledger": round(firm_b_cost.total_usd, 6),
        "firm_b_expected": round(firm_b_total, 6),
        "no_cross_firm_leak": (
            abs(firm_a_cost.total_usd - firm_a_total) < 1e-4
            and abs(firm_b_cost.total_usd - firm_b_total) < 1e-4
        ),
    }
    # Firm-A's recent-traces must not contain firm-B's sessions.
    cross_leak = bool(firm_a_session_ids & firm_b_session_ids)
    assertions["firm_scoping_traces_disjoint"] = not cross_leak

    # --- Headline summary ---
    headline_pass = all([
        assertions["all_traces_assembled"],
        assertions["min_timeline_len"] >= 4,
        assertions["cost_ledger_sums_match"],
        assertions["metrics_match_expected_engagement_count"],
        assertions["failure_diagnosable"],
        assertions["no_prose_in_logs"],
        assertions["no_prose_in_metrics"],
        assertions["no_prose_in_cost_ledger"],
        assertions["no_prose_in_traces"],
        assertions["firm_scoping_cost"]["no_cross_firm_leak"],
        assertions["firm_scoping_traces_disjoint"],
    ])
    assertions["headline_pass"] = headline_pass

    print()
    print("=== ASSERTIONS ===")
    for k, v in assertions.items():
        if isinstance(v, bool):
            status = "PASS" if v else "FAIL"
            print(f"  [{status}] {k}")
        elif isinstance(v, dict):
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: {v}")
    print()
    print(f"HEADLINE: {'PASS' if headline_pass else 'FAIL'}")

    # Render the dashboard payload + the Prometheus exposition for
    # the eval summary — confirms the W20/D5 API layer assembles
    # cleanly against the simulated load.
    prom_text = await metrics_mod.render_prometheus()
    summary = {
        "engagements": summaries,
        "assertions": assertions,
        "verification_distribution_pct": _compute_verdict_pct(verdict_dist),
        "prometheus_excerpt": prom_text.splitlines()[:30],
        "total_cost_across_all_engagements": round(
            sum(s["engagement_cost_total"] for s in summaries), 4,
        ),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2, default=str))
    print(f"summary written: {SUMMARY_PATH}")

    return 0 if headline_pass else 1


def _compute_verdict_pct(dist: dict[str, int]) -> dict[str, float]:
    total = sum(dist.values()) or 1
    supported = dist.get("supported_high", 0) + dist.get("supported_low", 0)
    partial = dist.get("weak", 0)
    insufficient = dist.get("contradicted", 0) + dist.get("unknown", 0)
    return {
        "supported_pct": round(supported / total * 100, 2),
        "partial_pct": round(partial / total * 100, 2),
        "insufficient_pct": round(insufficient / total * 100, 2),
        "total": total,
    }


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
