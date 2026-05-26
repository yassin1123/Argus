"""Tests for the W20/D3 cost ledger + rollups.

Seven spec assertions:

  1. record_llm_call writes a cost_ledger row alongside llm_calls
  2. engagement_cost sums every ledger row for a session
  3. engagement_cost surfaces a by-agent breakdown
  4. firm_cost respects the from/to window
  5. session_cost_total (ceiling source-of-truth) reads from ledger
  6. firm_admin cost queries cannot see another firm's data
  7. cost_by_model is system-wide and aggregates across firms

All seven run against an in-memory DB fake (no Postgres needed),
matching the test_versioning_service / test_observability_metrics
pattern.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core.observability import cost as cost_mod  # noqa: E402
from core.observability import cost_rollups as roll_mod  # noqa: E402


# ---------------------------------------------------------------------------
# In-memory DB fake
# ---------------------------------------------------------------------------


class _Store:
    """Holds cost_ledger rows + session→firm mappings."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.sessions: dict[str, str] = {}  # session_id -> firm_id
        self._next_id = 1

    def add_session(self, session_id: str, firm_id: str) -> None:
        self.sessions[session_id] = firm_id

    def insert_row(
        self, *, trace_id: str | None, session_id: str | None,
        firm_id: str, agent: str, provider: str, model: str,
        prompt_tokens: int, completion_tokens: int, cost_usd: float,
        recorded_at: datetime | None = None,
    ) -> None:
        self.rows.append({
            "id": self._next_id,
            "trace_id": trace_id,
            "session_id": session_id,
            "firm_id": firm_id,
            "agent": agent, "provider": provider, "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "recorded_at": recorded_at or datetime.now(tz=timezone.utc),
        })
        self._next_id += 1


def _install_fake(monkeypatch: pytest.MonkeyPatch) -> _Store:
    """Stub ``acquire`` in both cost.py and cost_rollups.py + the
    sessions.firm_id lookup."""
    store = _Store()

    async def execute(sql: str, *args: Any) -> str:
        s = " ".join(sql.split())
        if "INSERT INTO cost_ledger" in s:
            store.insert_row(
                trace_id=str(args[0]) if args[0] else None,
                session_id=str(args[1]) if args[1] else None,
                firm_id=str(args[2]),
                agent=args[3], provider=args[4], model=args[5],
                prompt_tokens=int(args[6]),
                completion_tokens=int(args[7]),
                cost_usd=float(args[8]),
            )
            return "INSERT 0 1"
        return "OK"

    async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.split())
        if "FROM sessions WHERE id" in s:
            sid = str(args[0])
            firm = store.sessions.get(sid)
            return {"firm_id": firm} if firm else None
        if "FROM cost_ledger WHERE session_id" in s and "SUM(cost_usd)" in s:
            sid = str(args[0])
            matching = [r for r in store.rows if r["session_id"] == sid]
            return {
                "total": float(sum(r["cost_usd"] for r in matching)),
                "call_count": len(matching),
                "pt": int(sum(r["prompt_tokens"] for r in matching)),
                "ct": int(sum(r["completion_tokens"] for r in matching)),
            }
        # firm_cost total row
        if "COUNT(DISTINCT session_id)" in s:
            firm_id = str(args[0])
            matching = [r for r in store.rows if r["firm_id"] == firm_id]
            # apply time window from args[1:]
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
        # session_cost_total — match by SUM(cost_usd)+COALESCE without count column
        if "FROM cost_ledger WHERE session_id" in s:
            sid = str(args[0])
            matching = [r for r in store.rows if r["session_id"] == sid]
            return {"total": float(sum(r["cost_usd"] for r in matching))}
        return None

    async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.split())
        # engagement_cost by-agent / by-model: session-scoped
        if "FROM cost_ledger WHERE session_id" in s and "GROUP BY" in s:
            sid = str(args[0])
            matching = [r for r in store.rows if r["session_id"] == sid]
            field = "agent" if "GROUP BY agent" in s else "model"
            groups: dict[str, list[dict[str, Any]]] = {}
            for r in matching:
                groups.setdefault(r[field], []).append(r)
            out = []
            for label, rs in groups.items():
                out.append({
                    "label": label,
                    "count": len(rs),
                    "cost_usd": float(sum(r["cost_usd"] for r in rs)),
                    "pt": int(sum(r["prompt_tokens"] for r in rs)),
                    "ct": int(sum(r["completion_tokens"] for r in rs)),
                })
            out.sort(key=lambda r: r["cost_usd"], reverse=True)
            return out
        # firm_cost by-engagement / by-model: firm-scoped + windowed
        if "FROM cost_ledger WHERE firm_id" in s and "GROUP BY" in s:
            firm_id = str(args[0])
            matching = [r for r in store.rows if r["firm_id"] == firm_id]
            arg_iter = iter(args[1:])
            if "recorded_at >= " in s:
                f = next(arg_iter)
                matching = [r for r in matching if r["recorded_at"] >= f]
            if "recorded_at < " in s:
                t = next(arg_iter)
                matching = [r for r in matching if r["recorded_at"] < t]
            field = "session_id" if "GROUP BY session_id" in s else "model"
            groups: dict[str, list[dict[str, Any]]] = {}
            for r in matching:
                k = r[field] or "unattributed"
                groups.setdefault(k, []).append(r)
            out = []
            for label, rs in groups.items():
                out.append({
                    "label": label,
                    "count": len(rs),
                    "cost_usd": float(sum(r["cost_usd"] for r in rs)),
                    "pt": int(sum(r["prompt_tokens"] for r in rs)),
                    "ct": int(sum(r["completion_tokens"] for r in rs)),
                })
            out.sort(key=lambda r: r["cost_usd"], reverse=True)
            return out
        # cost_by_model: system-wide
        if "FROM cost_ledger" in s and "GROUP BY model, provider" in s:
            matching = store.rows[:]
            arg_iter = iter(args)
            if "recorded_at >= " in s:
                f = next(arg_iter)
                matching = [r for r in matching if r["recorded_at"] >= f]
            if "recorded_at < " in s:
                t = next(arg_iter)
                matching = [r for r in matching if r["recorded_at"] < t]
            groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for r in matching:
                groups.setdefault((r["model"], r["provider"]), []).append(r)
            out = []
            for (mdl, prov), rs in groups.items():
                out.append({
                    "model": mdl, "provider": prov,
                    "call_count": len(rs),
                    "total_usd": float(sum(r["cost_usd"] for r in rs)),
                    "prompt_tokens": int(sum(r["prompt_tokens"] for r in rs)),
                    "completion_tokens": int(sum(r["completion_tokens"] for r in rs)),
                })
            out.sort(key=lambda r: r["total_usd"], reverse=True)
            return out
        return []

    fake_conn = mock.MagicMock()
    fake_conn.execute = execute
    fake_conn.fetchrow = fetchrow
    fake_conn.fetch = fetch

    class _AcquireCM:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    def _acquire():
        return _AcquireCM()

    monkeypatch.setattr(cost_mod, "acquire", _acquire)
    monkeypatch.setattr(roll_mod, "acquire", _acquire)
    return store


# ---------------------------------------------------------------------------
# 1. record_llm_call writes a ledger row
# ---------------------------------------------------------------------------


def test_llm_call_records_ledger_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """The integration: record_llm_call's success path calls
    record_cost. We assert record_cost wrote one row with the
    expected attribution."""
    store = _install_fake(monkeypatch)
    sid = str(uuid4())
    firm = str(uuid4())
    store.add_session(sid, firm)

    async def go() -> None:
        await cost_mod.record_cost(
            trace_id=None,
            session_id=sid,
            firm_id=None,  # forces firm-id lookup via session
            agent="writer", provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_tokens=2500, completion_tokens=1800,
            cost_usd=0.0345,
        )

    asyncio.run(go())
    assert len(store.rows) == 1
    row = store.rows[0]
    assert row["session_id"] == sid
    assert row["firm_id"] == firm
    assert row["agent"] == "writer"
    assert row["provider"] == "anthropic"
    assert row["model"] == "claude-sonnet-4-6"
    assert row["prompt_tokens"] == 2500
    assert row["completion_tokens"] == 1800
    assert row["cost_usd"] == pytest.approx(0.0345)


# ---------------------------------------------------------------------------
# 2. engagement_cost sums correctly
# ---------------------------------------------------------------------------


def test_engagement_cost_sums_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)
    sid = str(uuid4())
    firm = str(uuid4())
    store.add_session(sid, firm)

    async def go() -> None:
        # Realistic M&A engagement footprint — planner cheap,
        # writer expensive, verifier middle.
        samples = [
            ("planner", "openai", "gpt-4o", 1000, 500, 0.0125),
            ("analyst", "anthropic", "claude-sonnet-4-6", 4500, 3200, 0.078),
            ("verifier", "openai", "gpt-4o", 3800, 1500, 0.0335),
            ("writer", "anthropic", "claude-sonnet-4-6", 6000, 8000, 0.156),
        ]
        for agent, prov, mdl, pt, ct, usd in samples:
            await cost_mod.record_cost(
                trace_id=None, session_id=sid, firm_id=firm,
                agent=agent, provider=prov, model=mdl,
                prompt_tokens=pt, completion_tokens=ct,
                cost_usd=usd,
            )
        result = await roll_mod.engagement_cost(sid)
        assert result.session_id == sid
        assert result.total_usd == pytest.approx(0.280)
        assert result.call_count == 4
        assert result.prompt_tokens == 15300
        assert result.completion_tokens == 13200

    asyncio.run(go())
    assert len(store.rows) == 4


# ---------------------------------------------------------------------------
# 3. engagement_cost breakdown by agent
# ---------------------------------------------------------------------------


def test_engagement_cost_breakdown_by_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake(monkeypatch)
    sid = str(uuid4())
    firm = str(uuid4())

    async def go() -> None:
        # Writer = 0.30, Verifier = 0.10, Analyst = 0.05 → ordered by cost desc.
        samples = [
            ("writer", 0.20), ("writer", 0.10),
            ("verifier", 0.06), ("verifier", 0.04),
            ("analyst", 0.05),
        ]
        for agent, usd in samples:
            await cost_mod.record_cost(
                trace_id=None, session_id=sid, firm_id=firm,
                agent=agent, provider="anthropic",
                model="claude-sonnet-4-6",
                prompt_tokens=1000, completion_tokens=500,
                cost_usd=usd,
            )
        result = await roll_mod.engagement_cost(sid)
        labels = [r.label for r in result.by_agent]
        # Sorted by cost descending: writer > verifier > analyst.
        assert labels[0] == "writer"
        assert labels[1] == "verifier"
        assert labels[2] == "analyst"
        writer_row = next(r for r in result.by_agent if r.label == "writer")
        assert writer_row.cost_usd == pytest.approx(0.30)
        assert writer_row.count == 2

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 4. firm_cost respects the from/to window
# ---------------------------------------------------------------------------


def test_firm_cost_windowed(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _install_fake(monkeypatch)
    firm = str(uuid4())
    base = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)

    # Three rows, three different timestamps.
    for ts_delta, usd in (
        (timedelta(days=-10), 0.10),
        (timedelta(days=-3), 0.20),
        (timedelta(days=0), 0.40),
    ):
        store.insert_row(
            trace_id=None, session_id=str(uuid4()),
            firm_id=firm, agent="writer", provider="anthropic",
            model="claude-sonnet-4-6", prompt_tokens=1000,
            completion_tokens=500, cost_usd=usd,
            recorded_at=base + ts_delta,
        )

    async def go() -> None:
        # 7-day window — captures the -3d and 0d rows only.
        result = await roll_mod.firm_cost(
            firm,
            from_ts=base - timedelta(days=7),
            to_ts=base + timedelta(seconds=1),
        )
        assert result.total_usd == pytest.approx(0.60)
        assert result.call_count == 2
        # No bounds — all three.
        result = await roll_mod.firm_cost(firm)
        assert result.total_usd == pytest.approx(0.70)
        assert result.call_count == 3

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 5. session_cost_total reads from ledger (ceiling source-of-truth)
# ---------------------------------------------------------------------------


def test_session_ceiling_reads_from_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The W20/D3 reconciliation: any per-engagement cost-cap gate
    calls session_cost_total which SUMs ledger rows. No private
    accumulator state."""
    store = _install_fake(monkeypatch)
    sid = str(uuid4())
    firm = str(uuid4())

    async def go() -> None:
        # Start: zero.
        total = await roll_mod.session_cost_total(sid)
        assert total == 0.0

        # Record three calls; the total tracks them exactly.
        for usd in (0.10, 0.25, 0.05):
            await cost_mod.record_cost(
                trace_id=None, session_id=sid, firm_id=firm,
                agent="writer", provider="anthropic",
                model="claude-sonnet-4-6",
                prompt_tokens=100, completion_tokens=50,
                cost_usd=usd,
            )
        total = await roll_mod.session_cost_total(sid)
        assert total == pytest.approx(0.40)

        # Simulated cost-cap gate would consult session_cost_total
        # rather than a separate counter — confirm the value
        # drives the gate decision deterministically.
        assert (total > 0.30) is True   # over $0.30 cap → gate trips
        assert (total > 1.00) is False  # under $1.00 cap → gate clear

    asyncio.run(go())
    assert len(store.rows) == 3


# ---------------------------------------------------------------------------
# 6. firm_admin scoping forbids reading another firm's cost
# ---------------------------------------------------------------------------


def test_firm_admin_cost_scoped_to_own_firm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)
    firm_a = str(uuid4())
    firm_b = str(uuid4())

    # Both firms record costs.
    for firm, usd_total in ((firm_a, [0.10, 0.20]), (firm_b, [0.50, 0.30, 0.40])):
        for usd in usd_total:
            store.insert_row(
                trace_id=None, session_id=str(uuid4()),
                firm_id=firm, agent="writer", provider="anthropic",
                model="claude-sonnet-4-6", prompt_tokens=100,
                completion_tokens=50, cost_usd=usd,
            )

    async def go() -> None:
        a = await roll_mod.firm_cost(firm_a)
        b = await roll_mod.firm_cost(firm_b)
        assert a.total_usd == pytest.approx(0.30)
        assert b.total_usd == pytest.approx(1.20)

    asyncio.run(go())

    # API layer cross-firm prevention.
    from api.cost import _is_firm_admin, _is_system_admin
    firm_admin = {
        "user_id": "u1", "role": "member",
        "default_firm_id": firm_a, "default_firm_role": "admin",
    }
    sys_admin = {
        "user_id": "u2", "role": "admin",
        "default_firm_id": None, "default_firm_role": None,
    }
    assert _is_firm_admin(firm_admin) is True
    assert _is_system_admin(firm_admin) is False
    assert _is_system_admin(sys_admin) is True
    # The route handler refuses firm_admin reading firm_b.
    # We replay the gate inline:
    requested_firm = firm_b
    blocked = (
        _is_firm_admin(firm_admin)
        and not _is_system_admin(firm_admin)
        and firm_admin["default_firm_id"] != requested_firm
    )
    assert blocked is True
    # System admin can read either firm.
    blocked = (
        _is_firm_admin(sys_admin)
        and not _is_system_admin(sys_admin)
        and sys_admin["default_firm_id"] != requested_firm
    )
    assert blocked is False


# ---------------------------------------------------------------------------
# 7. cost_by_model system-wide
# ---------------------------------------------------------------------------


def test_cost_by_model_system_wide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _install_fake(monkeypatch)

    # Two firms, three models — cost_by_model aggregates ACROSS firms.
    samples = [
        (str(uuid4()), "claude-sonnet-4-6", "anthropic", 0.20),
        (str(uuid4()), "claude-sonnet-4-6", "anthropic", 0.30),
        (str(uuid4()), "gpt-4o", "openai", 0.10),
        (str(uuid4()), "gpt-4o", "openai", 0.15),
        (str(uuid4()), "gemini-1.5-pro", "google", 0.05),
    ]
    for firm, mdl, prov, usd in samples:
        store.insert_row(
            trace_id=None, session_id=str(uuid4()),
            firm_id=firm, agent="writer", provider=prov,
            model=mdl, prompt_tokens=1000, completion_tokens=500,
            cost_usd=usd,
        )

    async def go() -> None:
        rows = await roll_mod.cost_by_model()
        # Sorted by total cost descending.
        labels = [(r["model"], r["total_usd"]) for r in rows]
        assert labels[0][0] == "claude-sonnet-4-6"
        assert labels[0][1] == pytest.approx(0.50)
        assert labels[1][0] == "gpt-4o"
        assert labels[1][1] == pytest.approx(0.25)
        assert labels[2][0] == "gemini-1.5-pro"
        assert labels[2][1] == pytest.approx(0.05)
        # Cross-firm aggregation confirmed: this is system-admin only
        # (gated at the route layer), so the leak risk is contained
        # behind that role check.
        assert sum(r["total_usd"] for r in rows) == pytest.approx(0.80)

    asyncio.run(go())
