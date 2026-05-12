"""Phase 2 / Week 9 / Day 4 — mode-aware deepening tests.

Spec asks for four mode-aware tests plus permissions + cost-cap +
audit-event coverage. All DB-mocked so the suite runs without a live
Postgres or LLM client.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest

from core.consulting_modes import ResolvedConsultingMode
from core.section_deepening import (
    DeepeningRequest,
    MAX_DEEPENING_COST_USD,
    deepen_section,
)


# ---------------------------------------------------------------------------
# Fake DB infrastructure (same shape as W9/D1 test fixtures)
# ---------------------------------------------------------------------------


_M_AND_A_PAYLOAD: dict[str, Any] = {
    "recommendation": "Acquire TargetCo at £210m EV.",
    "confidence_level": "Medium-High",
    "summary": "M&A synthesis.",
    "key_reasons": ["Strong segment fit"] * 4,
    "risks": ["Integration risk"],
    "counterarguments": ["NRW TAM larger"],
    "next_steps": ["Sign LoI"] * 5,
    "sources": [{"title": "CIM", "type": "uploaded"}],
    "caveats": "",
    "consulting_payload": {
        "synergy_estimate": {
            "revenue_synergies": [],
            "cost_synergies": [
                {
                    "type": "procurement consolidation",
                    "magnitude_gbp_m": 8.5,
                    "timing_months": 12,
                    "confidence": "medium",
                    "basis_citations": ["c-proc-1"],
                },
            ],
            "dis_synergies": [],
            "net_present_value": {
                "low_gbp_m": 8.0,
                "base_gbp_m": 12.0,
                "high_gbp_m": 16.0,
                "discount_rate_pct": 11.5,
            },
            "realization_timeline": "24 months",
        },
    },
}

_GENERAL_PAYLOAD: dict[str, Any] = {
    "recommendation": "Run a Bavaria pilot.",
    "confidence_level": "Medium-High",
    "summary": "Bavaria pilot.",
    "key_reasons": [
        "Bavaria cycles faster than NRW.",
        "Three reference customers in-region.",
        "Pilot cost is bounded.",
        "Language overlap supports Austria phase 2.",
    ],
    "risks": ["Pilot scope creep."],
    "counterarguments": ["NRW TAM larger."],
    "next_steps": ["LoI", "Hire GTM", "Pricing", "Kill criteria", "Steering"],
    "sources": [{"title": "Bench 2025", "type": "research"}],
    "caveats": "",
    "consulting_payload": {},
}


def _fake_acquire(stored: dict[str, Any], *, report_mode: str, payload: dict[str, Any]):
    """Build a fake ``acquire()`` async ctx manager. Captures all
    SQL execs to ``stored['executes']`` and routes fetchrows to the
    expected shapes for the deepening service."""

    class _C:
        async def execute(self, sql: str, *args: Any) -> None:
            s = " ".join(sql.split()).lower()
            stored.setdefault("executes", []).append({"sql": s, "args": args})
            if "insert into section_deepening_runs" in s:
                stored["deepening_id"] = args[0]
                stored["section_path"] = args[3]
            elif "update section_deepening_runs set status='running'" in s:
                stored["status"] = "running"
            elif "update section_deepening_runs set status='complete'" in s:
                stored["status"] = "complete"
                stored["deepened_section_json"] = json.loads(args[1])
            elif "update section_deepening_runs set status='failed'" in s:
                stored["status"] = "failed"
                stored["failure_reason"] = args[1]
            elif "insert into audit_events" in s:
                stored.setdefault("audit", []).append({
                    "actor": args[0],
                    "action": args[1],
                    "resource": args[2],
                    "payload": json.loads(args[3]) if isinstance(args[3], str) else args[3],
                })

        async def fetchrow(self, sql: str, *args: Any) -> Any:
            s = " ".join(sql.split()).lower()
            if "from sessions where id" in s and "report_mode" in s:
                return {"report_mode": report_mode}
            if "from sessions where id" in s:
                return {"firm_id": stored.get("firm_id") or uuid4()}
            if "from reports where session_id" in s:
                base = {k: payload.get(k) for k in (
                    "recommendation", "confidence_level", "summary", "key_reasons",
                    "risks", "counterarguments", "next_steps", "sources", "caveats",
                )}
                base["consulting_payload"] = payload.get("consulting_payload") or {}
                return base
            return None

        async def fetch(self, *a: Any, **kw: Any) -> list[Any]:
            return []

    class _A:
        async def __aenter__(self) -> Any:
            return _C()

        async def __aexit__(self, *exc: Any) -> None:
            return None

    return lambda: _A()


def _resolved(mode_name: str, overlay: str = "", display_name: str | None = None) -> ResolvedConsultingMode:
    return ResolvedConsultingMode(
        name=mode_name,
        display_name=display_name or mode_name.replace("_", " ").title(),
        description="",
        required_branches=[],
        reasoning_slots=[],
        source_priorities_default=[],
        trust_tier_rules={},
        writer_overlay=overlay,
        planner_overlay="",
        layer_provenance={},
    )


# ---------------------------------------------------------------------------
# Test 1 — M&A synergy deepening: schema rejects bad output (missing basis_citations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_and_a_synergy_deepening_enforces_basis_citations() -> None:
    stored: dict[str, Any] = {"firm_id": uuid4()}
    fake_acq = _fake_acquire(stored, report_mode="m_and_a_diligence", payload=_M_AND_A_PAYLOAD)

    # LLM returns a deepened cost_synergies list whose first item is
    # missing the required ``basis_citations`` field. The schema
    # validator must reject.
    bad_output = json.dumps([
        {
            "type": "procurement consolidation expansion",
            "magnitude_gbp_m": 9.2,
            "timing_months": 12,
            "confidence": "high",
            # basis_citations intentionally missing
        },
    ])

    with mock.patch("core.section_deepening.service.acquire", new=fake_acq), \
         mock.patch("core.section_deepening.service.hybrid_search", new=mock.AsyncMock(return_value={"results": []})), \
         mock.patch("core.section_deepening.service.llm_call_for_task", new=mock.AsyncMock(return_value=bad_output)), \
         mock.patch("core.section_deepening.service.resolve_mode", new=mock.AsyncMock(return_value=_resolved("m_and_a_diligence"))):
        req = DeepeningRequest(
            session_id=uuid4(),
            section_path="synergy_estimate.cost_synergies",
            depth_directive="Add more cost synergies with better evidence.",
        )
        result = await deepen_section(req, uuid4())

    assert result.status == "failed", f"expected failed; got {result.status} ({result.failure_reason})"
    assert "schema validation" in (result.failure_reason or "").lower()
    assert "basis_citations" in (result.failure_reason or "")
    # And the audit event landed.
    actions = [a["action"] for a in (stored.get("audit") or [])]
    assert "section_deepening.triggered" in actions
    assert "section_deepening.failed" in actions
    # No 'completed' event on this failure path.
    assert "section_deepening.completed" not in actions


# ---------------------------------------------------------------------------
# Test 2 — M&A synergy deepening: schema accepts valid output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_and_a_synergy_deepening_succeeds_with_valid_payload() -> None:
    stored: dict[str, Any] = {"firm_id": uuid4()}
    fake_acq = _fake_acquire(stored, report_mode="m_and_a_diligence", payload=_M_AND_A_PAYLOAD)

    good_output = json.dumps([
        {
            "type": "procurement consolidation",
            "magnitude_gbp_m": 9.2,
            "timing_months": 12,
            "confidence": "high",
            "basis_citations": ["c-proc-1", "c-new-2"],
        },
        {
            "type": "shared services centralization",
            "magnitude_gbp_m": 4.0,
            "timing_months": 18,
            "confidence": "medium",
            "basis_citations": ["c-shared-1"],
        },
    ])

    with mock.patch("core.section_deepening.service.acquire", new=fake_acq), \
         mock.patch("core.section_deepening.service.hybrid_search", new=mock.AsyncMock(return_value={"results": []})), \
         mock.patch("core.section_deepening.service.llm_call_for_task", new=mock.AsyncMock(return_value=good_output)), \
         mock.patch("core.section_deepening.service.resolve_mode", new=mock.AsyncMock(return_value=_resolved("m_and_a_diligence"))):
        req = DeepeningRequest(
            session_id=uuid4(),
            section_path="synergy_estimate.cost_synergies",
            depth_directive="Add a second cost synergy.",
        )
        result = await deepen_section(req, uuid4())

    assert result.status == "complete", f"expected complete; got {result.status} ({result.failure_reason})"
    assert len(stored["deepened_section_json"]) == 2
    actions = [a["action"] for a in (stored.get("audit") or [])]
    assert "section_deepening.completed" in actions
    assert "section_deepening.failed" not in actions


# ---------------------------------------------------------------------------
# Test 3 — growth_strategy deepening uses the mode's writer_overlay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_growth_strategy_section_deepening_uses_growth_overlay() -> None:
    """Assert the writer prompt fed to the LLM contains the
    growth_strategy mode's writer_overlay verbatim."""
    captured: dict[str, Any] = {"firm_id": uuid4()}
    fake_acq = _fake_acquire(captured, report_mode="growth_strategy", payload=_GENERAL_PAYLOAD)
    overlay_text = "FIRM HOUSE STYLE: lead with the strategic ask, never with risks."

    async def capture_llm(task: str, *, system: str, user: str, **kw: Any) -> str:
        captured["user_msg"] = user
        captured["system_msg"] = system
        # Return a valid list[str] for key_reasons (≥1 entry to clear
        # any list min-length the schema imposes; GeneralReportPayload
        # has no min-length).
        return json.dumps(["Bavaria first.", "Mittelstand Q4 shift.", "Pilot bounded.", "Austria phase 2."])

    with mock.patch("core.section_deepening.service.acquire", new=fake_acq), \
         mock.patch("core.section_deepening.service.hybrid_search", new=mock.AsyncMock(return_value={"results": []})), \
         mock.patch("core.section_deepening.service.llm_call_for_task", new=capture_llm), \
         mock.patch("core.section_deepening.service.resolve_mode", new=mock.AsyncMock(return_value=_resolved("growth_strategy", overlay=overlay_text, display_name="Growth strategy"))):
        req = DeepeningRequest(
            session_id=uuid4(),
            section_path="key_reasons",
            depth_directive="Tighten the reasons; cite Bavaria-specific data.",
        )
        result = await deepen_section(req, uuid4())

    assert result.status == "complete"
    user_msg = captured["user_msg"]
    assert overlay_text in user_msg
    assert "Growth strategy" in user_msg
    assert "growth_strategy" in user_msg
    assert "key_reasons" in user_msg


# ---------------------------------------------------------------------------
# Test 4 — firm-override overlay flows into the deepening prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepening_inherits_firm_override_overlay() -> None:
    """If the firm-resolved mode carries an overlay (firm layer
    overrides + appends to built-in), the deepening writer prompt
    sees it. The resolver's job is to produce the merged overlay;
    here we just confirm the deepening pipeline doesn't drop it."""
    captured: dict[str, Any] = {"firm_id": uuid4()}
    fake_acq = _fake_acquire(captured, report_mode="growth_strategy", payload=_GENERAL_PAYLOAD)
    firm_overlay = (
        "ALBRIGHT & MARSH HOUSE OVERLAY: every section closes with a "
        "one-line 'partner question' in italics."
    )

    async def capture_llm(task: str, *, system: str, user: str, **kw: Any) -> str:
        captured["user_msg"] = user
        return json.dumps(["a", "b", "c", "d"])

    with mock.patch("core.section_deepening.service.acquire", new=fake_acq), \
         mock.patch("core.section_deepening.service.hybrid_search", new=mock.AsyncMock(return_value={"results": []})), \
         mock.patch("core.section_deepening.service.llm_call_for_task", new=capture_llm), \
         mock.patch("core.section_deepening.service.resolve_mode", new=mock.AsyncMock(return_value=_resolved("growth_strategy", overlay=firm_overlay))):
        req = DeepeningRequest(
            session_id=uuid4(),
            section_path="key_reasons",
            depth_directive="",
        )
        await deepen_section(req, uuid4())

    assert firm_overlay in captured["user_msg"]


# ---------------------------------------------------------------------------
# Test 5 — cost-cap pre-flight blocks over-budget calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_cap_blocks_pre_firing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-flight estimate is normally well under the $0.75 cap
    by design (section excerpt truncated to 6KB, retrieved chunks
    capped at 20 × 500 chars, overlay capped at 2500 chars). To
    prove the rejection path fires, lower the cap to $0.001 — any
    realistic prompt overshoots that.

    Asserts: status='failed', failure_reason names the cap,
    LLM was never called, audit event landed with cap_usd.
    """
    monkeypatch.setattr("core.section_deepening.service.MAX_DEEPENING_COST_USD", 0.001)

    captured: dict[str, Any] = {"firm_id": uuid4()}
    fake_acq = _fake_acquire(captured, report_mode="general", payload=_GENERAL_PAYLOAD)
    llm_spy = mock.AsyncMock()

    with mock.patch("core.section_deepening.service.acquire", new=fake_acq), \
         mock.patch("core.section_deepening.service.hybrid_search", new=mock.AsyncMock(return_value={"results": []})), \
         mock.patch("core.section_deepening.service.llm_call_for_task", new=llm_spy), \
         mock.patch("core.section_deepening.service.resolve_mode", new=mock.AsyncMock(return_value=_resolved("general"))):
        req = DeepeningRequest(
            session_id=uuid4(),
            section_path="key_reasons",
            depth_directive="Tighten the reasons.",
        )
        result = await deepen_section(req, uuid4())

    assert result.status == "failed"
    assert "exceeded_per_run_cost_cap" in (result.failure_reason or "")
    # LLM was never called.
    llm_spy.assert_not_called()
    # Audit event landed.
    actions = [a["action"] for a in (captured.get("audit") or [])]
    assert "section_deepening.cost_cap_exceeded" in actions
    cost_event = next(a for a in captured["audit"] if a["action"] == "section_deepening.cost_cap_exceeded")
    # Cap value in the audit payload matches what's currently set.
    assert cost_event["payload"]["cap_usd"] == 0.001
    # Confirm the spec constant (untouched in the module) is still 0.75.
    assert MAX_DEEPENING_COST_USD == 0.75


# ---------------------------------------------------------------------------
# Test 6 — audit events: triggered + completed land on the happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_triggered_and_completed_land_on_happy_path() -> None:
    captured: dict[str, Any] = {"firm_id": uuid4()}
    fake_acq = _fake_acquire(captured, report_mode="general", payload=_GENERAL_PAYLOAD)
    actor = uuid4()
    with mock.patch("core.section_deepening.service.acquire", new=fake_acq), \
         mock.patch("core.section_deepening.service.hybrid_search", new=mock.AsyncMock(return_value={"results": []})), \
         mock.patch("core.section_deepening.service.llm_call_for_task", new=mock.AsyncMock(return_value=json.dumps(["one", "two", "three"]))), \
         mock.patch("core.section_deepening.service.resolve_mode", new=mock.AsyncMock(return_value=_resolved("general"))):
        req = DeepeningRequest(
            session_id=uuid4(),
            section_path="key_reasons",
            depth_directive="Tighten.",
        )
        result = await deepen_section(req, actor)

    assert result.status == "complete"
    actions = [a["action"] for a in (captured.get("audit") or [])]
    assert actions[0] == "section_deepening.triggered"
    assert "section_deepening.completed" in actions
    # Triggered carries the actor (consultant); completed is system.
    triggered = next(a for a in captured["audit"] if a["action"] == "section_deepening.triggered")
    completed = next(a for a in captured["audit"] if a["action"] == "section_deepening.completed")
    assert triggered["actor"] == actor
    assert completed["actor"] is None


# ---------------------------------------------------------------------------
# Test 7 — section_path that doesn't exist on the schema fails cleanly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepening_on_section_not_in_schema_fails_cleanly() -> None:
    """The hard rule "don't run deepening on sections that don't
    exist in the current schema" is enforced at the schema-path
    layer — an M&A path on a general-mode engagement would fail
    the *payload-level* address walk first (no synergy_estimate
    in the payload), so this surfaces as SectionNotFoundError
    upstream. The path-vs-schema check inside validate is the
    second line of defence (if the runtime payload has been
    injected from elsewhere)."""
    captured: dict[str, Any] = {"firm_id": uuid4()}
    fake_acq = _fake_acquire(captured, report_mode="general", payload=_GENERAL_PAYLOAD)

    with mock.patch("core.section_deepening.service.acquire", new=fake_acq), \
         mock.patch("core.section_deepening.service.hybrid_search", new=mock.AsyncMock(return_value={"results": []})), \
         mock.patch("core.section_deepening.service.llm_call_for_task", new=mock.AsyncMock(return_value="[]")), \
         mock.patch("core.section_deepening.service.resolve_mode", new=mock.AsyncMock(return_value=_resolved("general"))):
        req = DeepeningRequest(
            session_id=uuid4(),
            section_path="synergy_estimate.cost_synergies",  # M&A-only
            depth_directive="",
        )
        result = await deepen_section(req, uuid4())

    assert result.status == "failed"
    # Either the addressing layer or the schema-path layer raises a
    # readable message naming the offending path.
    assert "synergy_estimate" in (result.failure_reason or "")
