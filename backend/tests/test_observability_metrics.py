"""Tests for the W20/D2 metrics layer.

Seven spec assertions:

  1. ``increment`` records counter rows + the query layer sums them
  2. ``observe`` records histogram samples + the query layer
     surfaces count + sum + avg
  3. ``llm.call`` rows are labelled by provider, model, agent
  4. ``verification.verdict`` rows aggregate by outcome
  5. ``query_window`` respects the from/to window
  6. firm-admin scoping forbids reading another firm's metrics
  7. Prometheus output is valid exposition-format text

All seven run against an in-memory fake DB that monkeypatches
``acquire`` in the metrics + API modules — matching the pattern
used by ``test_versioning_service.py`` (no Postgres needed).
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core.observability import metrics as metrics_mod  # noqa: E402
from core.observability import trace as trace_mod  # noqa: E402


# ---------------------------------------------------------------------------
# In-memory DB fake
# ---------------------------------------------------------------------------


class _Store:
    """Holds the rows + assigns ids the way the real INSERT would.
    Keeps the test surface honest — we can't accidentally rely on
    in-memory Python aggregation when the real query path is SQL."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._next_id = 1

    def insert(
        self, metric_name: str, labels: dict[str, Any], value: float,
        *, trace_id: str | None, firm_id: str | None,
        recorded_at: datetime | None = None,
    ) -> None:
        self.rows.append({
            "id": self._next_id,
            "metric_name": metric_name,
            "labels": labels,
            "value": value,
            "trace_id": trace_id,
            "firm_id": firm_id,
            "recorded_at": recorded_at or datetime.now(tz=timezone.utc),
        })
        self._next_id += 1


def _install_fake(monkeypatch: pytest.MonkeyPatch) -> _Store:
    """Install a stub ``acquire`` in :mod:`core.observability.metrics`
    that routes INSERT + SELECT to an in-memory store."""
    store = _Store()

    async def execute(sql: str, *args: Any) -> str:
        s = " ".join(sql.split())
        if "INSERT INTO metric_events" in s:
            metric_name = args[0]
            labels = json.loads(args[1]) if isinstance(args[1], str) else (args[1] or {})
            value = float(args[2])
            trace_id = str(args[3]) if args[3] else None
            firm_id = str(args[4]) if args[4] else None
            store.insert(
                metric_name, labels, value,
                trace_id=trace_id, firm_id=firm_id,
            )
            return "INSERT 0 1"
        return "OK"

    def _match(row: dict[str, Any], filters: dict[str, Any]) -> bool:
        for k, v in filters.items():
            if k == "from_ts":
                if row["recorded_at"] < v: return False
            elif k == "to_ts":
                if row["recorded_at"] >= v: return False
            elif k == "metric_name":
                if row["metric_name"] != v: return False
            elif k == "firm_id":
                if row["firm_id"] != v: return False
        return True

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        # SELECT DISTINCT metric_name FROM metric_events...
        if "SELECT DISTINCT metric_name" in s:
            firm = args[0] if args else None
            seen: set[str] = set()
            out: list[dict[str, Any]] = []
            for row in store.rows:
                if firm is not None and row["firm_id"] != str(firm):
                    continue
                if row["metric_name"] not in seen:
                    seen.add(row["metric_name"])
                    out.append({"metric_name": row["metric_name"]})
            out.sort(key=lambda r: r["metric_name"])
            return out
        # The aggregate query — parse out the filters from args.
        # Arg 0 is always metric_name; the rest depend on what
        # clauses were appended by query_window().
        metric_name = args[0]
        filters: dict[str, Any] = {"metric_name": metric_name}
        # The SQL builder appends in a fixed order: from_ts, to_ts,
        # firm_id, then group_by (which goes to the JSONB expr).
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

        matching = [r for r in store.rows if _match(r, filters)]
        if group_field is None:
            if not matching:
                return [{
                    "grp": None, "count": 0, "sum": 0.0, "avg": 0.0,
                    "min": 0.0, "max": 0.0,
                }]
            vals = [r["value"] for r in matching]
            return [{
                "grp": None,
                "count": len(vals),
                "sum": sum(vals),
                "avg": sum(vals) / len(vals),
                "min": min(vals),
                "max": max(vals),
            }]
        groups: dict[str | None, list[float]] = {}
        for r in matching:
            g = r["labels"].get(group_field) if isinstance(r["labels"], dict) else None
            groups.setdefault(g, []).append(r["value"])
        out = []
        for g, vals in groups.items():
            out.append({
                "grp": g,
                "count": len(vals),
                "sum": sum(vals),
                "avg": sum(vals) / len(vals),
                "min": min(vals),
                "max": max(vals),
            })
        out.sort(key=lambda r: r["count"], reverse=True)
        return out

    fake_conn = mock.MagicMock()
    fake_conn.execute = execute
    fake_conn.fetch = fetch

    class _AcquireCM:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    def _acquire():
        return _AcquireCM()

    monkeypatch.setattr(metrics_mod, "acquire", _acquire)
    return store


# ---------------------------------------------------------------------------
# 1. counter increments
# ---------------------------------------------------------------------------


def test_counter_increments(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake(monkeypatch)

    async def go() -> None:
        for _ in range(5):
            await metrics_mod.increment("engagement.started", {"mode": "m_and_a"})
        rows = await metrics_mod.query_window("engagement.started")
        assert rows == [{
            "group": None,
            "count": 5, "sum": 5.0, "avg": 1.0, "min": 1.0, "max": 1.0,
        }]
        # And a labelled query confirms the label propagated.
        rows = await metrics_mod.query_window(
            "engagement.started", group_by="mode",
        )
        assert len(rows) == 1
        assert rows[0]["group"] == "m_and_a"
        assert rows[0]["count"] == 5

    asyncio.run(go())
    assert len(store.rows) == 5
    assert all(r["value"] == 1.0 for r in store.rows)


# ---------------------------------------------------------------------------
# 2. histogram observes
# ---------------------------------------------------------------------------


def test_histogram_observes_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake(monkeypatch)

    async def go() -> None:
        for ms in (120.0, 145.0, 200.0, 88.0, 310.0):
            await metrics_mod.observe(
                "llm.latency_ms", ms,
                {"provider": "anthropic", "model": "claude-sonnet-4-6"},
            )
        rows = await metrics_mod.query_window("llm.latency_ms")
        assert rows[0]["count"] == 5
        assert rows[0]["sum"] == pytest.approx(863.0)
        assert rows[0]["min"] == 88.0
        assert rows[0]["max"] == 310.0
        assert rows[0]["avg"] == pytest.approx(172.6)

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 3. llm.call rows labelled by provider / model / agent
# ---------------------------------------------------------------------------


def test_llm_call_metric_labeled_by_provider_model_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch)

    async def go() -> None:
        # Mixed providers + agents — the standard shape the
        # litellm_client.record_llm_call() emit will land here in
        # production.
        samples = [
            ("anthropic", "claude-sonnet-4-6", "writer"),
            ("anthropic", "claude-sonnet-4-6", "writer"),
            ("anthropic", "claude-sonnet-4-6", "analyst"),
            ("openai", "gpt-4o", "verifier"),
            ("openai", "gpt-4o", "verifier"),
            ("google", "gemini-1.5-pro", "planner"),
        ]
        for provider, model, agent in samples:
            await metrics_mod.increment(
                "llm.call",
                {"provider": provider, "model": model, "agent": agent},
            )
        # Group by provider.
        by_provider = await metrics_mod.query_window(
            "llm.call", group_by="provider",
        )
        counts = {r["group"]: r["count"] for r in by_provider}
        assert counts == {"anthropic": 3, "openai": 2, "google": 1}
        # Group by agent — verifier should be 2.
        by_agent = await metrics_mod.query_window(
            "llm.call", group_by="agent",
        )
        agent_counts = {r["group"]: r["count"] for r in by_agent}
        assert agent_counts["verifier"] == 2
        assert agent_counts["writer"] == 2
        # Group by model — claude-sonnet-4-6 should be 3.
        by_model = await metrics_mod.query_window(
            "llm.call", group_by="model",
        )
        model_counts = {r["group"]: r["count"] for r in by_model}
        assert model_counts["claude-sonnet-4-6"] == 3

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 4. verification.verdict distribution
# ---------------------------------------------------------------------------


def test_verification_verdict_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch)

    async def go() -> None:
        # Counts mimic a real pipeline's verdict histogram.
        verdicts = {
            "supported_high": 20, "supported_low": 6,
            "weak": 3, "contradicted": 1,
        }
        for verdict, n in verdicts.items():
            await metrics_mod.increment(
                "verification.verdict",
                {"outcome": verdict, "mode": "m_and_a"},
                value=n,
            )
        rows = await metrics_mod.query_window(
            "verification.verdict", group_by="outcome",
        )
        out = {r["group"]: r["sum"] for r in rows}
        assert out == {
            "supported_high": 20.0, "supported_low": 6.0,
            "weak": 3.0, "contradicted": 1.0,
        }

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 5. time-windowed query
# ---------------------------------------------------------------------------


def test_metrics_query_time_windowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)
    base = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)

    # Seed three rows at different times by hand-inserting (we
    # need control over recorded_at to test the window).
    store.insert("llm.call", {"provider": "openai"}, 1.0,
                 trace_id=None, firm_id=None,
                 recorded_at=base - timedelta(hours=3))
    store.insert("llm.call", {"provider": "openai"}, 1.0,
                 trace_id=None, firm_id=None,
                 recorded_at=base - timedelta(hours=1))
    store.insert("llm.call", {"provider": "openai"}, 1.0,
                 trace_id=None, firm_id=None,
                 recorded_at=base + timedelta(hours=1))

    async def go() -> None:
        # 2-hour window ending at base — should see exactly the
        # middle row.
        rows = await metrics_mod.query_window(
            "llm.call",
            from_ts=base - timedelta(hours=2),
            to_ts=base,
        )
        assert rows[0]["count"] == 1
        # No bounds — sees all three.
        rows = await metrics_mod.query_window("llm.call")
        assert rows[0]["count"] == 3

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 6. firm-admin scoping forbids reading another firm's metrics
# ---------------------------------------------------------------------------


def test_firm_admin_sees_only_own_firm_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)
    firm_a = str(uuid4())
    firm_b = str(uuid4())

    # Both firms record llm.call rows.
    for firm, n in ((firm_a, 5), (firm_b, 12)):
        for _ in range(n):
            store.insert(
                "llm.call",
                {"provider": "anthropic", "firm_id": firm},
                1.0, trace_id=None, firm_id=firm,
            )

    async def go() -> None:
        # firm-admin of firm_a should only see firm_a's rows.
        rows = await metrics_mod.query_window("llm.call", firm_id=firm_a)
        assert rows[0]["count"] == 5
        # firm-admin of firm_b only firm_b.
        rows = await metrics_mod.query_window("llm.call", firm_id=firm_b)
        assert rows[0]["count"] == 12
        # System-admin (no firm filter) sees both.
        rows = await metrics_mod.query_window("llm.call")
        assert rows[0]["count"] == 17

    asyncio.run(go())

    # Cross-firm leak prevention at the API layer — _scope_firm_id
    # must FORCE a firm_admin to their own firm regardless of the
    # query-param they send.
    from api.metrics import _scope_firm_id

    firm_admin = {
        "user_id": "u1", "role": "member",
        "default_firm_id": firm_a, "default_firm_role": "admin",
    }
    # Caller tries to read firm_b's metrics — we MUST ignore the
    # param and force firm_a.
    assert _scope_firm_id(firm_admin, firm_b) == firm_a
    assert _scope_firm_id(firm_admin, None) == firm_a

    sys_admin = {
        "user_id": "u2", "role": "admin",
        "default_firm_id": None, "default_firm_role": None,
    }
    # System admin can scope to any firm + can run cross-firm.
    assert _scope_firm_id(sys_admin, firm_b) == firm_b
    assert _scope_firm_id(sys_admin, None) is None


# ---------------------------------------------------------------------------
# 7. Prometheus exposition format
# ---------------------------------------------------------------------------


def test_prometheus_endpoint_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch)

    async def go() -> None:
        # Seed both a counter + a histogram-style metric.
        for _ in range(3):
            await metrics_mod.increment(
                "engagement.started", {"mode": "m_and_a"},
            )
        for ms in (100.0, 200.0, 300.0):
            await metrics_mod.observe(
                "llm.latency_ms", ms,
                {"provider": "anthropic"},
            )
        text = await metrics_mod.render_prometheus()
        # Must be ASCII text with the standard HELP/TYPE preamble
        # per Prometheus exposition format.
        assert "# TYPE" in text
        assert "# HELP" in text
        # Counter rendered with _total suffix + the dot translated
        # to an underscore.
        assert "engagement_started_total" in text
        # Histogram-style metric rendered as a summary with count + sum.
        assert "llm_latency_ms_count" in text
        assert "llm_latency_ms_sum" in text
        # No metric name carries a literal dot (Prometheus parsers
        # reject ``.`` in metric names).
        for line in text.splitlines():
            if line.startswith("#"):
                continue
            stripped = line.strip()
            if not stripped:
                continue
            name = stripped.split()[0].split("{")[0]
            assert "." not in name, f"dot left in metric name: {line!r}"

    asyncio.run(go())
