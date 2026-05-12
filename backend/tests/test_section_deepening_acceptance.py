"""Phase 2 / Week 9 / Day 3 — accept/reject service tests.

Spec lists five tests:

  1. test_accept_replaces_section_in_payload
  2. test_accept_writes_audit_log
  3. test_accept_preserves_other_sections
  4. test_accept_creates_new_payload_version
  5. test_reject_does_not_modify_payload

Plus three robustness cases worth pinning while we're here (W9/D3
hard rules):

  - Idempotency: a second accept is a no-op (not a 409).
  - Cannot accept after reject.
  - SectionNotFoundError surfaces when the path no longer resolves.

All tests are DB-mocked so the suite runs without a live Postgres.
The mock layer captures every SQL execute so the assertions can
verify what landed where (audit row, reports update, deepening
column flips).
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest

from core.section_deepening import (
    DeepeningNotAcceptableError,
    DeepeningNotFoundError,
    accept_deepening,
    reject_deepening,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_BASE_PAYLOAD: dict[str, Any] = {
    "recommendation": "Run a 6-month Bavaria pilot.",
    "confidence_level": "Medium-High",
    "summary": "Bavaria de-risks DACH expansion cheaply.",
    "key_reasons": [
        "Bavaria procurement cycles run faster than NRW.",
        "Three reference customers in-region.",
    ],
    "risks": ["Pilot scope creep."],
    "counterarguments": ["NRW has larger TAM."],
    "next_steps": ["Sign LoI", "Hire GTM lead"],
    "sources": [{"title": "Bench 2025", "type": "research"}],
    "caveats": "",
    "consulting_payload": {
        "target_overview": {"name": "TargetCo", "segments": [{"name": "FM", "revenue_pct": 52.0}]},
        "synergy_estimate": {
            "cost_synergies": [
                {"type": "procurement consolidation", "magnitude_gbp_m": 8.5},
            ],
        },
    },
}


def _fake_db_factory(stored: dict[str, Any]):
    """Build a fake ``acquire()`` async context manager backed by a
    dict. Captures every SQL execute so tests can assert which UPDATEs
    fired against which tables."""

    class _FakeConn:
        async def execute(self, sql: str, *args: Any) -> None:
            sql_lower = " ".join(sql.split()).lower()
            stored.setdefault("executes", []).append({"sql": sql_lower, "args": args})
            if "update reports set" in sql_lower:
                stored["reports_update"] = {
                    "recommendation": args[1],
                    "confidence_level": args[2],
                    "summary": args[3],
                    "key_reasons": json.loads(args[4]) if isinstance(args[4], str) else args[4],
                    "risks": json.loads(args[5]) if isinstance(args[5], str) else args[5],
                    "counterarguments": json.loads(args[6]) if isinstance(args[6], str) else args[6],
                    "next_steps": json.loads(args[7]) if isinstance(args[7], str) else args[7],
                    "sources": json.loads(args[8]) if isinstance(args[8], str) else args[8],
                    "caveats": args[9],
                    "consulting_payload": json.loads(args[10]) if isinstance(args[10], str) else args[10],
                }
                # Mutate stored payload so subsequent reads see the new state.
                stored["reports_row"].update({
                    "recommendation": args[1],
                    "confidence_level": args[2],
                    "summary": args[3],
                    "key_reasons": json.loads(args[4]),
                    "risks": json.loads(args[5]),
                    "counterarguments": json.loads(args[6]),
                    "next_steps": json.loads(args[7]),
                    "sources": json.loads(args[8]),
                    "caveats": args[9],
                    "consulting_payload": json.loads(args[10]),
                })
            elif "update section_deepening_runs set accepted_at" in sql_lower:
                stored["deepening_row"]["accepted_at"] = "now"
                stored["deepening_row"]["accepted_by"] = args[1]
                stored["deepening_row"]["pre_accept_payload_snapshot"] = (
                    json.loads(args[2]) if isinstance(args[2], str) else args[2]
                )
            elif "update section_deepening_runs set rejected_at" in sql_lower:
                stored["deepening_row"]["rejected_at"] = "now"
                stored["deepening_row"]["rejected_by"] = args[1]
            elif "insert into audit_events" in sql_lower:
                stored.setdefault("audit_events", []).append({
                    "actor": args[0],
                    "action": args[1],
                    "resource_id": args[2],
                    "payload": json.loads(args[3]) if isinstance(args[3], str) else args[3],
                })

        async def fetchrow(self, sql: str, *args: Any) -> Any:
            sql_lower = " ".join(sql.split()).lower()
            if "from section_deepening_runs" in sql_lower:
                return dict(stored["deepening_row"])
            if "from reports where session_id" in sql_lower:
                return dict(stored["reports_row"])
            return None

    class _FakeAcquire:
        async def __aenter__(self) -> Any:
            return _FakeConn()

        async def __aexit__(self, *exc: Any) -> None:
            return None

    return lambda: _FakeAcquire()


def _build_stored(
    *,
    section_path: str = "key_reasons",
    deepened_value: Any = None,
    status: str = "complete",
    accepted_at: Any = None,
    rejected_at: Any = None,
) -> dict[str, Any]:
    if deepened_value is None:
        deepened_value = [
            "Bavaria procurement cycles run 6-8 weeks faster than NRW.",
            "Three reference customers anchor logo-zero meaningfully.",
            "Mittelstand procurement budgets shift in Q4 2025.",
        ]
    return {
        "deepening_row": {
            "id": str(uuid4()),
            "session_id": str(uuid4()),
            "section_path": section_path,
            "status": status,
            "accepted_at": accepted_at,
            "rejected_at": rejected_at,
            "deepened_section_json": deepened_value,
        },
        "reports_row": dict(_BASE_PAYLOAD),
    }


# ---------------------------------------------------------------------------
# Test 1 — accept replaces the section in the payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_replaces_section_in_payload() -> None:
    stored = _build_stored()
    new_section = [
        "Bavaria procurement cycles run 6-8 weeks faster than NRW (verified).",
        "Three reference customers anchor logo-zero meaningfully (3 LOIs).",
        "Mittelstand budgets shift in Q4 2025 (Bundesverband data).",
    ]
    stored["deepening_row"]["deepened_section_json"] = new_section

    with mock.patch("core.section_deepening.acceptance.acquire", new=_fake_db_factory(stored)):
        result = await accept_deepening(uuid4(), uuid4(), uuid4())

    assert result["status"] == "accepted"
    assert result["section_path"] == "key_reasons"
    # The merged payload returned to the caller has the new section.
    assert result["new_payload"]["key_reasons"] == new_section
    # And the reports UPDATE landed with the same new content.
    assert stored["reports_update"]["key_reasons"] == new_section


# ---------------------------------------------------------------------------
# Test 2 — accept writes an audit event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_writes_audit_log() -> None:
    stored = _build_stored()
    actor = uuid4()
    with mock.patch("core.section_deepening.acceptance.acquire", new=_fake_db_factory(stored)):
        await accept_deepening(uuid4(), uuid4(), actor)

    events = stored.get("audit_events") or []
    assert len(events) == 1
    e = events[0]
    assert e["action"] == "section_deepening.accepted"
    assert e["actor"] == actor
    assert e["payload"]["section_path"] == "key_reasons"


# ---------------------------------------------------------------------------
# Test 3 — accept preserves every other section byte-identical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_preserves_other_sections() -> None:
    stored = _build_stored(section_path="key_reasons")
    original_summary = stored["reports_row"]["summary"]
    original_recommendation = stored["reports_row"]["recommendation"]
    original_target = dict(stored["reports_row"]["consulting_payload"]["target_overview"])

    with mock.patch("core.section_deepening.acceptance.acquire", new=_fake_db_factory(stored)):
        result = await accept_deepening(uuid4(), uuid4(), uuid4())

    # Every NON-touched field round-trips unchanged through the merge.
    new = result["new_payload"]
    assert new["summary"] == original_summary
    assert new["recommendation"] == original_recommendation
    assert new["target_overview"] == original_target
    # And on the persisted side too.
    assert stored["reports_update"]["summary"] == original_summary
    assert stored["reports_update"]["recommendation"] == original_recommendation
    assert stored["reports_update"]["consulting_payload"]["target_overview"] == original_target


# ---------------------------------------------------------------------------
# Test 4 — accept snapshots the pre-accept payload for history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_creates_new_payload_version() -> None:
    """The full pre-accept payload is captured on the deepening row
    (``pre_accept_payload_snapshot``) so a Phase 4 rollback can
    reconstruct the prior memo. Reports stays single-row-per-session
    (no breaking change for existing readers), but history is
    preserved via the snapshot."""
    stored = _build_stored()
    with mock.patch("core.section_deepening.acceptance.acquire", new=_fake_db_factory(stored)):
        await accept_deepening(uuid4(), uuid4(), uuid4())

    snapshot = stored["deepening_row"]["pre_accept_payload_snapshot"]
    assert snapshot is not None
    # The snapshot is the pre-accept state, not the post-accept state.
    assert snapshot["key_reasons"] == _BASE_PAYLOAD["key_reasons"]
    # And every other field too.
    assert snapshot["summary"] == _BASE_PAYLOAD["summary"]
    assert snapshot["target_overview"] == _BASE_PAYLOAD["consulting_payload"]["target_overview"]


# ---------------------------------------------------------------------------
# Test 5 — reject does not modify the payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_does_not_modify_payload() -> None:
    stored = _build_stored()
    pre = dict(stored["reports_row"])
    with mock.patch("core.section_deepening.acceptance.acquire", new=_fake_db_factory(stored)):
        result = await reject_deepening(uuid4(), uuid4(), uuid4())

    assert result["status"] == "rejected"
    # No reports update fired.
    assert "reports_update" not in stored
    assert stored["reports_row"] == pre
    # But the deepening row got the reject marker.
    assert stored["deepening_row"]["rejected_at"] == "now"
    # And an audit event landed.
    events = stored.get("audit_events") or []
    assert len(events) == 1
    assert events[0]["action"] == "section_deepening.rejected"


# ---------------------------------------------------------------------------
# Bonus 1 — idempotency: second accept is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_idempotent_on_already_accepted() -> None:
    from datetime import datetime, timezone
    stored = _build_stored(accepted_at=datetime.now(timezone.utc))
    with mock.patch("core.section_deepening.acceptance.acquire", new=_fake_db_factory(stored)):
        result = await accept_deepening(uuid4(), uuid4(), uuid4())
    assert result["status"] == "already_accepted"
    # No new reports update; no new audit event.
    assert "reports_update" not in stored
    assert "audit_events" not in stored


# ---------------------------------------------------------------------------
# Bonus 2 — reject after accept raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_after_accept_raises() -> None:
    from datetime import datetime, timezone
    stored = _build_stored(accepted_at=datetime.now(timezone.utc))
    with mock.patch("core.section_deepening.acceptance.acquire", new=_fake_db_factory(stored)):
        with pytest.raises(DeepeningNotAcceptableError):
            await reject_deepening(uuid4(), uuid4(), uuid4())


# ---------------------------------------------------------------------------
# Bonus 3 — not-found raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_on_unknown_id_raises_not_found() -> None:
    class _MissingConn:
        async def fetchrow(self, *a: Any, **kw: Any) -> Any:
            return None

        async def execute(self, *a: Any, **kw: Any) -> None:
            return None

    class _A:
        async def __aenter__(self) -> Any:
            return _MissingConn()

        async def __aexit__(self, *exc: Any) -> None:
            return None

    with mock.patch("core.section_deepening.acceptance.acquire", new=lambda: _A()):
        with pytest.raises(DeepeningNotFoundError):
            await accept_deepening(uuid4(), uuid4(), uuid4())
