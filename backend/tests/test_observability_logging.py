"""Tests for the W20/D1 observability layer.

Covers the six spec assertions:

  1. log lines are valid JSON
  2. trace_id propagates through the contextvars context
  3. redact() strips claim / evidence / memo prose from every payload
  4. pipeline stages emit the expected structured events with trace_id
  5. the FastAPI middleware logs request.start + request.complete
  6. a fresh run_id distinguishes two re-runs of the same session
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
import types
from pathlib import Path

import pytest

# Make ``backend`` importable when pytest is launched from the repo root.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core.observability.logging import (  # noqa: E402
    REDACTED_VALUE,
    configure_event_logging,
    emit_event,
    redact,
    reset_configuration_for_tests,
)
from core.observability.trace import (  # noqa: E402
    TraceContext,
    bind_trace_context,
    new_run_id,
    new_trace_id,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def capture_buf() -> io.StringIO:
    """Reinstall the event logger so it writes to an in-memory buffer."""
    reset_configuration_for_tests()
    buf = io.StringIO()
    configure_event_logging(stream=buf)
    yield buf
    reset_configuration_for_tests()


def _read_lines(buf: io.StringIO) -> list[dict]:
    raw = buf.getvalue().strip().splitlines()
    return [json.loads(line) for line in raw if line.strip()]


# ---------------------------------------------------------------------------
# 1. log line is valid JSON
# ---------------------------------------------------------------------------


def test_log_line_is_valid_json(capture_buf: io.StringIO) -> None:
    """Every emitted line must be a JSON object that parses cleanly
    and carries the standard envelope keys (timestamp, level, event)."""
    emit_event(
        "planner.complete",
        duration_ms=42.0,
        task_count=7,
    )
    lines = _read_lines(capture_buf)
    assert len(lines) == 1
    line = lines[0]
    assert line["event"] == "planner.complete"
    assert line["level"] == "INFO"
    assert isinstance(line["timestamp"], str) and "T" in line["timestamp"]
    assert line["duration_ms"] == 42.0
    # Structured fields land under ``data``.
    assert line["data"]["task_count"] == 7


# ---------------------------------------------------------------------------
# 2. trace_id propagates through context
# ---------------------------------------------------------------------------


def test_trace_id_propagates_through_context(capture_buf: io.StringIO) -> None:
    """The trace_id bound via :func:`bind_trace_context` must appear
    on every log line emitted inside its scope — including across
    nested ``await`` calls, simulating the pipeline's downstream
    coroutines."""
    tid = new_trace_id()

    async def _inner() -> None:
        # No new binding here — relying on contextvars propagation.
        emit_event("planner.complete", task_count=3)

    async def _outer() -> None:
        with bind_trace_context(
            trace_id=tid,
            session_id="sess-1",
            firm_id="firm-1",
        ):
            emit_event("pipeline.start", report_mode="m_and_a")
            await _inner()
            emit_event("pipeline.complete", unsupported_claims=0)

    asyncio.run(_outer())

    lines = _read_lines(capture_buf)
    assert [l["event"] for l in lines] == [
        "pipeline.start", "planner.complete", "pipeline.complete",
    ]
    for line in lines:
        assert line["trace_id"] == tid
        assert line["session_id"] == "sess-1"
        assert line["firm_id"] == "firm-1"


# ---------------------------------------------------------------------------
# 3. redact() strips claim / evidence / memo prose
# ---------------------------------------------------------------------------


def test_redact_strips_claim_text(capture_buf: io.StringIO) -> None:
    """The hard privacy guarantee: no field carrying claim text,
    evidence content, or memo prose may appear in the JSON output.

    Tested both on the standalone :func:`redact` (unit-level) and
    via :func:`emit_event` (integration through the logger)."""

    # --- Unit: every banned field name gets replaced ---
    payload = {
        "claim_id": "c123",
        "claim_text": "Q2 revenue grew 14% YoY",
        "evidence_text": "...from the 10-Q filing...",
        "evidence_excerpt": "...long passage...",
        "memo_prose": "Our recommendation is to proceed.",
        "writer_output": "Full memo body here.",
        "snippet": "tiny snippet",
        "claim_count": 4,
        "model_name": "claude-sonnet-4-6",
        "nested": {
            "raw_text": "evidence chunk content here",
            "trust_score": 0.92,
            "list": [
                {"section_text": "Section prose"},
                {"section_path": "summary"},
            ],
        },
    }
    out = redact(payload)
    # Every banned field is replaced with [REDACTED].
    assert out["claim_text"] == REDACTED_VALUE
    assert out["evidence_text"] == REDACTED_VALUE
    assert out["evidence_excerpt"] == REDACTED_VALUE
    assert out["memo_prose"] == REDACTED_VALUE
    assert out["writer_output"] == REDACTED_VALUE
    assert out["snippet"] == REDACTED_VALUE
    assert out["nested"]["raw_text"] == REDACTED_VALUE
    assert out["nested"]["list"][0]["section_text"] == REDACTED_VALUE
    # Safe fields survive unchanged.
    assert out["claim_id"] == "c123"
    assert out["claim_count"] == 4
    assert out["model_name"] == "claude-sonnet-4-6"
    assert out["nested"]["trust_score"] == 0.92
    assert out["nested"]["list"][1]["section_path"] == "summary"

    # --- Integration: emit_event must redact before writing ---
    emit_event(
        "verifier.complete",
        claim_text="this should never appear",
        evidence_excerpt="neither should this",
        memo_prose="nor this",
        verdict_distribution={"supported_high": 5, "weak": 2},
    )
    lines = _read_lines(capture_buf)
    assert len(lines) == 1
    serialized = json.dumps(lines[0])
    # The banned source strings must NOT be in the output anywhere.
    assert "this should never appear" not in serialized
    assert "neither should this" not in serialized
    assert "nor this" not in serialized
    # Sentinels in their place + safe fields preserved.
    assert lines[0]["data"]["claim_text"] == REDACTED_VALUE
    assert lines[0]["data"]["evidence_excerpt"] == REDACTED_VALUE
    assert lines[0]["data"]["memo_prose"] == REDACTED_VALUE
    assert lines[0]["data"]["verdict_distribution"] == {
        "supported_high": 5, "weak": 2,
    }


# ---------------------------------------------------------------------------
# 4. pipeline stages emit structured events
# ---------------------------------------------------------------------------


def test_pipeline_stages_emit_structured_events(
    capture_buf: io.StringIO,
) -> None:
    """Simulate the orchestrator's stage sequence with the same
    ``emit_event`` calls it makes in production. Asserts the full
    stage event names appear in order with trace_id stamped on
    every line."""
    tid = new_trace_id()
    with bind_trace_context(
        trace_id=tid,
        session_id="sess-pipeline",
        firm_id="firm-1",
    ):
        emit_event("pipeline.start", report_mode="m_and_a")
        emit_event("planner.complete", duration_ms=120.0, task_count=8)
        emit_event(
            "retrieval.complete",
            duration_ms=4500.0,
            evidence_count=42,
            evidence_by_source={"sec_filing": 20, "transcripts": 12, "news": 10},
        )
        emit_event(
            "analyst.complete",
            duration_ms=8200.0,
            claim_count=37,
            pass_label="v1",
        )
        emit_event(
            "verifier.complete",
            duration_ms=15000.0,
            verdict_distribution={
                "supported_high": 25, "supported_low": 8, "weak": 3, "contradicted": 1,
            },
            assessments_total=37,
        )
        emit_event(
            "writer.complete",
            duration_ms=6100.0,
            report_mode="m_and_a",
            payload_bytes=18432,
        )
        emit_event(
            "artifacts.generated",
            duration_ms=900.0,
            artifact_count=1,
            artifact_kinds=["memo"],
        )
        emit_event(
            "pipeline.complete",
            duration_ms=35000.0,
            unsupported_claims=1,
            contradiction_severity="low",
        )

    lines = _read_lines(capture_buf)
    expected = [
        "pipeline.start",
        "planner.complete",
        "retrieval.complete",
        "analyst.complete",
        "verifier.complete",
        "writer.complete",
        "artifacts.generated",
        "pipeline.complete",
    ]
    assert [l["event"] for l in lines] == expected
    for line in lines:
        assert line["trace_id"] == tid
        assert line["session_id"] == "sess-pipeline"
    # The verifier event must carry a verdict_distribution dict + a total.
    verifier = next(l for l in lines if l["event"] == "verifier.complete")
    assert verifier["data"]["verdict_distribution"]["supported_high"] == 25
    assert verifier["data"]["assessments_total"] == 37


# ---------------------------------------------------------------------------
# 5. middleware logs request.start + request.complete
# ---------------------------------------------------------------------------


def test_request_middleware_logs_start_and_complete(
    capture_buf: io.StringIO,
) -> None:
    """The trace middleware must emit ``request.start`` on entry,
    ``request.complete`` on exit, and tag the response header with
    the trace_id. The trace_id seeded by the middleware must be
    visible to handlers via :func:`get_trace_context`."""
    from core.observability.middleware import trace_middleware, TRACE_HEADER
    from core.observability.trace import get_trace_context

    # Minimal Request / Response stand-ins (we don't want a real
    # ASGI app for a unit-level test).
    class _Resp:
        def __init__(self, status: int = 200) -> None:
            self.status_code = status
            self.headers: dict[str, str] = {}

    class _Headers(dict):
        # Case-insensitive get to match Starlette's Headers.
        def get(self, k, default=None):
            for kk in (k, k.lower(), k.title()):
                if kk in self:
                    return super().__getitem__(kk)
            return default

    class _Req:
        def __init__(self, method="POST", path="/api/sessions/abc/run") -> None:
            self.method = method
            self.url = types.SimpleNamespace(path=path)
            self.headers = _Headers()

    seen_trace_id: dict[str, str] = {}

    async def _handler(_req: _Req) -> _Resp:
        # Confirm the middleware bound the context before us.
        ctx = get_trace_context()
        seen_trace_id["value"] = ctx.trace_id or ""
        return _Resp(status=200)

    resp = asyncio.run(trace_middleware(_Req(), _handler))  # type: ignore[arg-type]
    assert resp.status_code == 200
    assert resp.headers.get(TRACE_HEADER), "response must carry X-Trace-Id"
    assert seen_trace_id["value"] == resp.headers[TRACE_HEADER]

    lines = _read_lines(capture_buf)
    events = [l["event"] for l in lines]
    assert "request.start" in events
    assert "request.complete" in events
    # Both lines must carry the same trace_id.
    start = next(l for l in lines if l["event"] == "request.start")
    complete = next(l for l in lines if l["event"] == "request.complete")
    assert start["trace_id"] == complete["trace_id"]
    assert complete["trace_id"] == resp.headers[TRACE_HEADER]
    # The complete event must carry a duration + status.
    assert complete["duration_ms"] >= 0
    assert complete["data"]["status"] == 200
    assert complete["data"]["route"] == "/api/sessions/abc/run"


# ---------------------------------------------------------------------------
# 6. run_id distinguishes two reruns of the same session
# ---------------------------------------------------------------------------


def test_run_id_distinguishes_reruns(capture_buf: io.StringIO) -> None:
    """Two pipeline runs against the same session must produce
    distinct run_id values (so we can scope analytics per execution
    even when the session itself is re-used)."""
    sid = "sess-rerun"
    tid = new_trace_id()

    run_ids: list[str] = []
    for _ in range(2):
        rid = new_run_id()
        run_ids.append(rid)
        with bind_trace_context(
            trace_id=tid, run_id=rid, session_id=sid,
        ):
            emit_event("pipeline.start", report_mode="m_and_a")
            emit_event(
                "pipeline.complete",
                duration_ms=10.0,
                unsupported_claims=0,
            )

    lines = _read_lines(capture_buf)
    assert len(run_ids) == 2
    assert run_ids[0] != run_ids[1]
    # Group events by run_id; each group must contain start + complete.
    by_run: dict[str, list[str]] = {}
    for line in lines:
        by_run.setdefault(line["run_id"], []).append(line["event"])
    assert sorted(by_run.keys()) == sorted(run_ids)
    for rid, evs in by_run.items():
        assert evs == ["pipeline.start", "pipeline.complete"]
        # All same trace_id, same session, distinct run_id.
        for line in lines:
            if line["run_id"] == rid:
                assert line["trace_id"] == tid
                assert line["session_id"] == sid
