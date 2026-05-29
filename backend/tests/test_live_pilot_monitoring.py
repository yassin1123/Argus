"""Live-pilot monitoring tests — Phase 5 / Week 25 / Day 2.

Live-DB integration tests (per-test UUIDs + cleanup). Pin four
contracts:

  1. the live-pilot view shows active (in-flight) engagements,
  2. an alert fires on an engagement failure,
  3. an alert fires on a budget threshold (80% / 100%),
  4. an anomalous verification distribution is flagged.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from core.pilot_monitoring import (
    detect_verification_anomaly,
    evaluate_pilot_alerts,
    live_pilot_view,
)


@pytest.fixture(autouse=True)
async def _db_pool():
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


async def _make_firm(suffix: str) -> str:
    from db.connection import acquire
    firm_id = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO firms (id, name, slug) VALUES ($1::uuid, $2, $3)",
            firm_id, f"LivePilot {suffix}", f"livepilot-{suffix}",
        )
    return firm_id


async def _add_session(firm_id: str, status: str, title: str = "eng") -> str:
    from db.connection import acquire
    sid = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions (id, firm_id, title, query, status) "
            "VALUES ($1::uuid, $2::uuid, $3, 'q', $4)",
            sid, firm_id, title, status,
        )
    return sid


async def _cleanup(firm_id: str) -> None:
    from db.connection import acquire
    async with acquire() as conn:
        await conn.execute("DELETE FROM cost_ledger WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM sessions WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM firms WHERE id = $1::uuid", firm_id)


# ---------------------------------------------------------------------------
# 1. live view shows active engagements
# ---------------------------------------------------------------------------


async def test_live_pilot_dashboard_shows_active_engagements() -> None:
    fid = await _make_firm(uuid.uuid4().hex[:8])
    try:
        active = await _add_session(fid, "processing", "running now")
        await _add_session(fid, "complete", "done earlier")

        view = await live_pilot_view(fid)
        assert view["firm_id"] == fid
        ids = {e["session_id"]: e for e in view["active_engagements"]}
        assert active in ids
        assert ids[active]["active"] is True
        assert ids[active]["status"] == "processing"
        # The view carries the standard live panels.
        assert "cost_burn" in view and "alerts" in view
        assert "verification_distribution" in view and "feedback" in view
    finally:
        await _cleanup(fid)


# ---------------------------------------------------------------------------
# 2. alert fires on engagement failure
# ---------------------------------------------------------------------------


async def test_alert_fires_on_engagement_failure() -> None:
    fid = await _make_firm(uuid.uuid4().hex[:8])
    try:
        await _add_session(fid, "failed", "blew up")
        alerts = await evaluate_pilot_alerts(fid)
        kinds = {a.kind for a in alerts}
        assert "engagement_failure" in kinds
        fail = next(a for a in alerts if a.kind == "engagement_failure")
        assert fail.severity == "critical"
        assert fail.data["failed"] >= 1
    finally:
        await _cleanup(fid)


# ---------------------------------------------------------------------------
# 3. alert fires on budget threshold
# ---------------------------------------------------------------------------


async def test_alert_fires_on_budget_threshold() -> None:
    from db.connection import acquire
    fid = await _make_firm(uuid.uuid4().hex[:8])
    try:
        sid = await _add_session(fid, "complete", "spendy")
        async with acquire() as conn:
            await conn.execute(
                "UPDATE firms SET monthly_budget_usd = 10.0 WHERE id = $1::uuid", fid,
            )
            # Drive month-to-date spend to 100%+.
            await conn.execute(
                """
                INSERT INTO cost_ledger
                    (firm_id, session_id, agent, provider, model,
                     prompt_tokens, completion_tokens, cost_usd)
                VALUES ($1::uuid, $2::uuid, 'analyst', 'anthropic',
                        'claude-opus', 100, 100, 10.5)
                """,
                fid, sid,
            )
        alerts = await evaluate_pilot_alerts(fid)
        budget = [a for a in alerts if a.kind == "budget_threshold"]
        assert budget, "expected a budget_threshold alert at >=100%"
        assert budget[0].severity == "critical"
        assert budget[0].data["blocks_new_engagements"] is True
    finally:
        await _cleanup(fid)


# ---------------------------------------------------------------------------
# 4. anomalous verification distribution flagged
# ---------------------------------------------------------------------------


async def test_anomalous_verification_distribution_flagged() -> None:
    # Pure-function checks — no DB needed for the detector itself.
    # Everything-insufficient over a real sample is an anomaly.
    anomalous, reason = detect_verification_anomaly(
        {"total": 12, "supported_pct": 0.0, "partial_pct": 8.0,
         "insufficient_pct": 92.0},
    )
    assert anomalous is True
    assert "insufficient" in reason.lower()

    # A healthy mix is not flagged.
    ok, _ = detect_verification_anomaly(
        {"total": 20, "supported_pct": 55.0, "partial_pct": 35.0,
         "insufficient_pct": 10.0},
    )
    assert ok is False

    # Too small a sample never flags (avoid false alarms early in a run).
    small, _ = detect_verification_anomaly(
        {"total": 3, "supported_pct": 0.0, "partial_pct": 0.0,
         "insufficient_pct": 100.0},
    )
    assert small is False

    # And it surfaces through evaluate_pilot_alerts when wired with a dist.
    fid = await _make_firm(uuid.uuid4().hex[:8])
    try:
        alerts = await evaluate_pilot_alerts(
            fid,
            verification_distribution={
                "total": 15, "supported_pct": 0.0, "partial_pct": 5.0,
                "insufficient_pct": 95.0,
            },
        )
        assert any(a.kind == "verification_anomaly" for a in alerts)
    finally:
        await _cleanup(fid)
