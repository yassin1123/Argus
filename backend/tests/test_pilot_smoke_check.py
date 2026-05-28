"""Pilot smoke-check tests — Phase 5 / Week 24 / Day 4.

Live-DB integration tests. Pin three contracts:

  1. all-green on a healthy system (keys present, DB up, a sample
     engagement with a full artifact set seeded),
  2. RED when the verifier key is missing in strict mode (the W23
     fail-loud — never a silent degrade),
  3. the report is a well-formed structured readiness document.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for p in (str(_REPO / "backend"), str(_REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.pilot_smoke_check import (
    ReadinessReport,
    check_config,
    run_smoke_check,
)


@pytest.fixture(autouse=True)
async def _db_pool():
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


async def _seed_ready_engagement() -> tuple[str, str]:
    """Seed a firm + a ready engagement with a full ready-artifact set,
    so check_sample_engagement is green independent of demo data.
    Returns (firm_id, session_id)."""
    from db.connection import acquire

    firm_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    pairs = [
        ("memo", "html"), ("one_pager", "pdf"), ("deck", "pptx"),
        ("excel_model", "xlsx"), ("email", "md"), ("interview_guide", "md"),
    ]
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO firms (id, name, slug) VALUES ($1::uuid, $2, $3)",
            firm_id, "Smoke Firm", f"smoke-{firm_id[:8]}",
        )
        await conn.execute(
            "INSERT INTO sessions (id, firm_id, title, query, status) "
            "VALUES ($1::uuid, $2::uuid, 'Smoke', 'q', 'ready')",
            session_id, firm_id,
        )
        for atype, fmt in pairs:
            await conn.execute(
                """
                INSERT INTO export_artifacts
                    (session_id, firm_id, artifact_type, format, status)
                VALUES ($1::uuid, $2::uuid, $3, $4, 'ready')
                """,
                session_id, firm_id, atype, fmt,
            )
    return firm_id, session_id


async def _cleanup(firm_id: str) -> None:
    from db.connection import acquire

    async with acquire() as conn:
        await conn.execute(
            "DELETE FROM export_artifacts WHERE firm_id = $1::uuid", firm_id,
        )
        await conn.execute("DELETE FROM sessions WHERE firm_id = $1::uuid", firm_id)
        await conn.execute("DELETE FROM firms WHERE id = $1::uuid", firm_id)


# ---------------------------------------------------------------------------
# 1. All green on a healthy system
# ---------------------------------------------------------------------------


async def test_smoke_check_all_green_on_healthy_system() -> None:
    firm_id, _ = await _seed_ready_engagement()
    try:
        report = await run_smoke_check()
        # Every check must pass on a healthy, key-present system.
        reds = [c for c in report.checks if c.status == "red"]
        assert not reds, f"unexpected red checks: {[(c.name, c.detail) for c in reds]}"
        assert report.overall_status == "green", (
            f"overall={report.overall_status}; "
            f"checks={[(c.name, c.status) for c in report.checks]}"
        )
        names = {c.name for c in report.checks}
        assert {
            "config", "database", "observability", "artifact_generators",
            "notifications", "audit_log", "sample_engagement",
        } <= names
    finally:
        await _cleanup(firm_id)


# ---------------------------------------------------------------------------
# 2. RED on a missing verifier key (fail-loud)
# ---------------------------------------------------------------------------


async def test_smoke_check_red_on_missing_key() -> None:
    from core import config as cfg

    snap = {
        k: os.environ.get(k) for k in (
            "ARGUS_MODE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        )
    }
    try:
        os.environ["ARGUS_MODE"] = "pilot"
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        cfg.validate_at_boot()  # refresh the cached report

        result = await check_config()
        assert result.status == "red", (
            "missing keys in pilot mode must be RED, never a silent degrade"
        )

        # The overall report is RED too when config (critical) is red.
        report = await run_smoke_check(checks=[check_config])
        assert report.overall_status == "red"
    finally:
        for k, v in snap.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cfg.validate_at_boot()


# ---------------------------------------------------------------------------
# 3. Structured readiness report
# ---------------------------------------------------------------------------


async def test_smoke_check_returns_structured_report() -> None:
    report = await run_smoke_check()
    assert isinstance(report, ReadinessReport)
    d = report.to_dict()
    assert d["overall_status"] in ("green", "yellow", "red")
    assert "generated_at" in d
    # Summary counts present + consistent.
    s = d["summary"]
    assert s["total"] == len(d["checks"])
    assert s["green"] + s["yellow"] + s["red"] == s["total"]
    # Each check carries the structured fields.
    for c in d["checks"]:
        assert c["name"]
        assert c["status"] in ("green", "yellow", "red")
        assert c["severity"] in ("critical", "optional")
        assert "detail" in c
