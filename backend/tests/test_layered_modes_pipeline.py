"""Phase 2 / Week 6 / Day 4 — integration tests for the layered consulting-
mode wiring through planner / writer / critic / research orchestrator.

Each test mocks the LLM call (``generate_structured``) so we can capture
the exact system + user prompts the agent emitted, then assert the
firm-resolved mode flowed through correctly. No live DB and no live LLM
calls — keeps the suite fast and CI-friendly.

The 6th test is a golden test against the built-in YAML: resolve_mode
without a firm/engagement layer must equal load_mode_legacy.
"""

from __future__ import annotations

import json
import pathlib
import textwrap
from typing import Any
from unittest.mock import AsyncMock

import pytest

from core.consulting_modes import (
    ResolvedConsultingMode,
    load_mode_legacy,
    resolve_mode,
)
from core.consulting_modes import resolver as resolver_mod


@pytest.fixture(autouse=True)
def _yaml_and_cache_reset(monkeypatch: pytest.MonkeyPatch):
    """Each test starts with the production YAML and an empty cache."""
    resolver_mod._yaml_reset()
    yield
    resolver_mod._yaml_reset()


def _patch_loaders(
    monkeypatch: pytest.MonkeyPatch,
    *,
    firm: dict[str, Any] | None = None,
    engagement: tuple[str, dict[str, Any]] | None = None,
) -> None:
    async def _firm_stub(name: str, firm_id: Any) -> dict[str, Any] | None:
        return firm

    async def _eng_stub(eng_id: Any, name: str) -> dict[str, Any] | None:
        if engagement is None:
            return None
        if engagement[0] != name:
            return None
        return engagement[1]

    monkeypatch.setattr(resolver_mod, "_load_firm_override", _firm_stub)
    monkeypatch.setattr(resolver_mod, "_load_engagement_override", _eng_stub)


# ---------------------------------------------------------------------------
# Common: patch generate_structured to capture system + user prompts.
# ---------------------------------------------------------------------------


class _Captured:
    system: str = ""
    user: str = ""
    task_kind: str = ""


def _patch_generate_structured(monkeypatch: pytest.MonkeyPatch, return_value: Any):
    captured = _Captured()

    async def _stub(model_cls, *, task_kind, system, user, **_):  # noqa: ARG001
        captured.task_kind = task_kind
        captured.system = system
        captured.user = user
        # ``return_value`` is a dict; coerce into the requested model.
        try:
            return model_cls.model_validate(return_value), {}
        except Exception:
            # Fall back to constructing an instance from defaults.
            return model_cls.model_construct(**return_value), {}

    # Patch in every agent module that has its own import of
    # generate_structured (planner, writer, critic).
    import agents.planner as planner_mod
    import agents.writer as writer_mod
    import agents.critic as critic_mod

    monkeypatch.setattr(planner_mod, "generate_structured", _stub)
    monkeypatch.setattr(writer_mod, "generate_structured", _stub)
    monkeypatch.setattr(critic_mod, "generate_structured", _stub)
    return captured


# ---------------------------------------------------------------------------
# Test 1 — planner uses the firm's required_branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_uses_firm_required_branches(monkeypatch):
    _patch_loaders(
        monkeypatch,
        firm={
            "required_branches": ["custom_branch_a", "custom_branch_b"],
            "writer_overlay": "Always conclude with a 90-day implementation roadmap.",
            "planner_overlay": "Prefer firm_library content for methodology questions.",
        },
    )
    resolved = await resolve_mode("growth_strategy", firm_id="11111111-1111-1111-1111-111111111111")
    assert resolved.required_branches == ["custom_branch_a", "custom_branch_b"]
    assert resolved.layer_provenance["required_branches"] == "firm"

    captured = _patch_generate_structured(
        monkeypatch,
        {
            "objective": "x",
            "tasks": [
                {
                    "id": 1,
                    "question": "x",
                    "type": "factual",
                    "priority": "high",
                    "why_it_matters": "x",
                    "source_priorities": ["uploaded"],
                }
            ],
            "decision_criteria": ["a"],
            "scope": "x",
        },
    )

    from agents.planner import PlannerAgent

    await PlannerAgent().run(
        query="What is the growth strategy?",
        context="",
        report_mode="growth_strategy",
        resolved_mode=resolved,
    )

    # Firm's branches show up in the planner's user message hint.
    assert "custom_branch_a" in captured.user
    assert "custom_branch_b" in captured.user
    # Built-in's branches (market, capabilities) DO NOT appear.
    assert "market, capabilities" not in captured.user
    # Planner overlay is appended to the system prompt.
    assert "Prefer firm_library content for methodology questions." in captured.system


# ---------------------------------------------------------------------------
# Test 2 — writer system prompt carries the firm's writer_overlay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_includes_overlay_phrasing(monkeypatch):
    _patch_loaders(
        monkeypatch,
        firm={
            "writer_overlay": "Always conclude with a 90-day implementation roadmap.",
            "display_name": "Firm A Growth Strategy",
        },
    )
    resolved = await resolve_mode("growth_strategy", firm_id="11111111-1111-1111-1111-111111111111")
    assert "90-day implementation roadmap" in resolved.writer_overlay

    captured = _patch_generate_structured(
        monkeypatch,
        # Minimal WriterReportPayload — using model_construct in the stub.
        {
            "recommendation": "x",
            "confidence_level": "Medium",
            "summary": "x",
            "key_reasons": [],
            "risks": [],
            "counterarguments": [],
            "next_steps": [],
            "sources": [],
            "caveats": "",
        },
    )

    from agents.writer import WriterAgent

    await WriterAgent().run(
        query="q",
        analysis={},
        critique={},
        research={},
        resolved_mode=resolved,
    )

    # The overlay is in the system prompt.
    assert "90-day implementation roadmap" in captured.system
    assert "FIRM WRITER OVERLAY" in captured.system
    # The mode header shows the firm-set display_name on the user message.
    assert "Firm A Growth Strategy" in captured.user


# ---------------------------------------------------------------------------
# Test 3 — critic gets firm's required_branches in coverage block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critic_checks_firm_branches(monkeypatch):
    _patch_loaders(
        monkeypatch,
        firm={
            "required_branches": ["custom_branch_a", "custom_branch_b"],
            "reasoning_slots": ["thesis_fit", "exit_clarity"],
        },
    )
    resolved = await resolve_mode("growth_strategy", firm_id="11111111-1111-1111-1111-111111111111")

    captured = _patch_generate_structured(
        monkeypatch,
        {
            "overall_assessment": "x",
            "revision_instructions": [],
            "weak_points": [],
            "counterarguments": [],
            "missing_evidence": [],
            "risks_missed": [],
            "confidence_adjustment": "stay",
            "verdict": "accept",
        },
    )

    from agents.critic import CriticAgent

    await CriticAgent().run(
        query="q",
        analysis={},
        research={},
        resolved_mode=resolved,
    )

    # Firm's branches AND reasoning slots appear in the critic's user message.
    assert "custom_branch_a" in captured.user
    assert "custom_branch_b" in captured.user
    assert "thesis_fit" in captured.user
    assert "exit_clarity" in captured.user
    # Built-in growth_strategy branches must NOT appear.
    assert "market, capabilities" not in captured.user


# ---------------------------------------------------------------------------
# Test 4 — research orchestrator falls back to mode source_priorities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orchestrator_uses_firm_source_priorities(monkeypatch):
    """A planner task without explicit source_priorities must fall back
    to the resolved mode's source_priorities_default."""
    _patch_loaders(
        monkeypatch,
        firm={"source_priorities_default": ["uploaded", "ch_filing"]},
    )
    resolved = await resolve_mode("market_entry", firm_id="11111111-1111-1111-1111-111111111111")

    captured_priorities: list[list[str]] = []

    async def _stub_retrieve(session_id, q, priorities):  # noqa: ARG001
        captured_priorities.append(list(priorities))
        return [], list(priorities)

    import agents.research.orchestrator as ro_mod

    monkeypatch.setattr(ro_mod, "_retrieve_by_priorities", _stub_retrieve)
    # Stop the post-priority paths from hitting real services.
    monkeypatch.setattr(ro_mod, "SERPAPI_KEY", "")  # disables web fetch branch
    # Skip required-branch planning by stubbing the helper to return [].
    async def _stub_branches(_plan, _req):  # noqa: ARG001
        return []
    monkeypatch.setattr(ro_mod, "_plan_research_branches", _stub_branches)
    # Skip _synthesize_finding LLM call.
    async def _stub_synth(q, objs):  # noqa: ARG001
        return {"finding": "stub", "confidence": "high", "gaps": ""}
    monkeypatch.setattr(ro_mod, "_synthesize_finding", _stub_synth)

    plan = {
        "objective": "test",
        "tasks": [
            # No source_priorities -> must fall back to resolved.source_priorities_default
            {"id": 1, "question": "What's the market?", "type": "factual"},
        ],
    }
    await ro_mod.ResearchOrchestrator().run(
        session_id="00000000-0000-0000-0000-000000000099",
        plan=plan,
        context="",
        report_mode="market_entry",
        resolved_mode=resolved,
    )

    assert captured_priorities, "expected _retrieve_by_priorities to be called"
    assert captured_priorities[0] == ["uploaded", "ch_filing"]


# ---------------------------------------------------------------------------
# Test 5 — engagement override stacks on top of firm override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engagement_override_layers_on_firm_override(monkeypatch):
    """Both firm and engagement override the same field; engagement wins.
    For lists, this is full replace (per Day 1 merge semantics)."""
    _patch_loaders(
        monkeypatch,
        firm={
            "required_branches": ["firm_a", "firm_b"],
            "writer_overlay": "Firm voice.",
        },
        engagement=(
            "growth_strategy",
            {
                # Engagement adds a regulatory branch — but lists are full
                # replace, so the engagement layer must declare the FULL
                # list it wants.
                "required_branches": ["firm_a", "firm_b", "regulatory"],
                "writer_overlay": "And add a regulatory annex.",
            },
        ),
    )
    resolved = await resolve_mode(
        "growth_strategy",
        firm_id="11111111-1111-1111-1111-111111111111",
        engagement_id="22222222-2222-2222-2222-222222222222",
    )

    # Engagement layer fully replaced firm's list.
    assert resolved.required_branches == ["firm_a", "firm_b", "regulatory"]
    assert resolved.layer_provenance["required_branches"] == "engagement"
    # Overlay appends: built_in (empty) + firm + engagement.
    assert resolved.writer_overlay == "Firm voice.\n\nAnd add a regulatory annex."
    assert resolved.layer_provenance["writer_overlay"] == "engagement"


# ---------------------------------------------------------------------------
# Test 6 — no firm override = identical to legacy YAML behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_firm_override_uses_builtin_unchanged(monkeypatch):
    """Backward-compat golden: every YAML mode resolved with no firm
    override returns the same data as the legacy shim."""
    _patch_loaders(monkeypatch, firm=None)

    raw = resolver_mod._load_yaml()
    assert raw, "production YAML should not be empty"

    for name in raw.keys():
        legacy = load_mode_legacy(name)
        layered = await resolve_mode(name, firm_id="33333333-3333-3333-3333-333333333333")
        assert layered.name == legacy.name
        assert layered.required_branches == legacy.required_branches
        assert layered.reasoning_slots == legacy.reasoning_slots
        assert layered.source_priorities_default == legacy.source_priorities_default
        assert layered.trust_tier_rules == legacy.trust_tier_rules
        assert layered.writer_overlay == legacy.writer_overlay
        assert layered.planner_overlay == legacy.planner_overlay
        assert layered.min_evidence_objects == legacy.min_evidence_objects
        assert all(v == "built_in" for v in layered.layer_provenance.values())
