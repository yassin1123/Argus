"""Phase 2 / Week 7 / Day 3 — writer dispatcher tests.

Hermetic — no DB, no LLM. We patch ``generate_structured`` directly
on ``agents.writer.agent`` and assert the WriterAgent picks the
right schema for the resolved mode and surfaces specific field-
level errors when the LLM returns shape-broken output.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from agents.writer import (
    GeneralReportPayload,
    MAndADiligenceReportPayload,
    WriterAgent,
)
from agents.writer.agent import WriterSchemaValidationError
from core.consulting_modes import ResolvedConsultingMode
from core.inference.exceptions import InferenceSchemaError

# Reuse the W7/D1 fixture builders so we don't drift from canonical shapes.
from tests.test_writer_schemas import _general_payload_json, _ma_payload_json


def _resolved(name: str) -> ResolvedConsultingMode:
    """Build a minimal ResolvedConsultingMode with just enough fields
    for the writer's prompt-selection + schema-selection paths."""
    return ResolvedConsultingMode(
        name=name,
        display_name=name,
        description="",
        required_branches=[],
        reasoning_slots=[],
        source_priorities_default=[],
        trust_tier_rules={},
        writer_overlay="",
        planner_overlay="",
        min_evidence_objects=0,
        metadata={},
        layer_provenance={
            "display_name": "built_in",
            "description": "built_in",
            "required_branches": "built_in",
            "reasoning_slots": "built_in",
            "source_priorities_default": "built_in",
            "trust_tier_rules": "built_in",
            "writer_overlay": "built_in",
            "planner_overlay": "built_in",
        },
    )


def _make_stub(*, payloads: list[dict[str, Any]], fail_count: int = 0):
    """Build a `generate_structured` stub that returns successive
    payloads and fails the first ``fail_count`` calls with a
    ValidationError raised through InferenceSchemaError (mirrors what
    the real generate_structured does on exhaustion).

    Returns (stub, capture) — capture is a dict that records call
    counts and the schema_cls each call was made against.
    """
    capture = {"calls": 0, "schemas": []}
    payload_iter = iter(payloads)

    async def _stub(model_cls, *, task_kind, system, user, **_):  # noqa: ARG001
        capture["calls"] += 1
        capture["schemas"].append(model_cls)
        if capture["calls"] <= fail_count:
            # Mirror the real failure surface: raise InferenceSchemaError
            # with a chained ValidationError. The writer must unwrap.
            try:
                model_cls.model_validate({})
            except ValidationError as ve:
                raise InferenceSchemaError("Schema validation failed") from ve
            raise InferenceSchemaError("Schema validation failed")
        nxt = next(payload_iter)
        return model_cls.model_validate(nxt), {}

    return _stub, capture


# ---------------------------------------------------------------------------
# 1. test_writer_uses_m_and_a_schema_for_m_and_a_mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_uses_m_and_a_schema_for_m_and_a_mode(monkeypatch):
    stub, cap = _make_stub(payloads=[_ma_payload_json()])
    import agents.writer.agent as agent_mod

    monkeypatch.setattr(agent_mod, "generate_structured", stub)

    out = await WriterAgent().run(
        query="acquire?",
        analysis={},
        critique={},
        research={},
        resolved_mode=_resolved("m_and_a_diligence"),
    )
    assert isinstance(out, MAndADiligenceReportPayload)
    assert cap["schemas"][0] is MAndADiligenceReportPayload
    # The mode-specific recommendation phrasing made it through.
    assert out.target_overview.name


# ---------------------------------------------------------------------------
# 2. test_writer_uses_general_schema_for_other_modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_uses_general_schema_for_other_modes(monkeypatch):
    stub, cap = _make_stub(payloads=[_general_payload_json()])
    import agents.writer.agent as agent_mod

    monkeypatch.setattr(agent_mod, "generate_structured", stub)

    out = await WriterAgent().run(
        query="grow?",
        analysis={},
        critique={},
        research={},
        resolved_mode=_resolved("growth_strategy"),
    )
    assert isinstance(out, GeneralReportPayload)
    assert not isinstance(out, MAndADiligenceReportPayload)
    assert cap["schemas"][0] is GeneralReportPayload


# ---------------------------------------------------------------------------
# 3. test_writer_retry_on_schema_validation_failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_retry_on_schema_validation_failure(monkeypatch):
    """``generate_structured`` itself owns the per-call repair loop —
    on the writer side we either get a clean payload back or an
    ``InferenceSchemaError`` once exhaustion fires. Verify the
    success path: when the upstream finally returns a valid payload,
    the writer just hands it back."""
    stub, cap = _make_stub(payloads=[_general_payload_json()])
    import agents.writer.agent as agent_mod

    monkeypatch.setattr(agent_mod, "generate_structured", stub)

    out = await WriterAgent().run(
        query="x",
        analysis={},
        critique={},
        research={},
        resolved_mode=_resolved("general"),
    )
    assert isinstance(out, GeneralReportPayload)
    assert cap["calls"] == 1


# ---------------------------------------------------------------------------
# 4. test_writer_surfaces_specific_failure_field_on_double_failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_writer_surfaces_specific_failure_field_on_double_failure(monkeypatch):
    """When ``generate_structured`` exhausts its retries and raises
    ``InferenceSchemaError`` with a chained ``ValidationError``, the
    writer must re-raise as ``WriterSchemaValidationError`` with the
    schema class name and the offending field path. A stack trace
    that says only "Schema validation failed after N repairs" is not
    diagnostic enough; the operator needs to see WHICH field broke."""
    stub, _cap = _make_stub(payloads=[], fail_count=1)
    import agents.writer.agent as agent_mod

    monkeypatch.setattr(agent_mod, "generate_structured", stub)

    with pytest.raises(WriterSchemaValidationError) as exc:
        await WriterAgent().run(
            query="x",
            analysis={},
            critique={},
            research={},
            resolved_mode=_resolved("m_and_a_diligence"),
        )
    msg = str(exc.value)
    assert "MAndADiligenceReportPayload" in msg
    # ValidationError on an empty dict cites at least one of the
    # required top-level fields (recommendation / target_overview /
    # financial_profile / etc.). The exact first field depends on
    # Pydantic ordering; we just assert *something* meaningful made
    # it into the message.
    assert exc.value.field_path != "(root)"
    assert exc.value.field_path != "(no validation error attached)"
