"""Structured-output round-trip tests across the new multi-provider routing.

Phase 1 / Week 1, Day 2.

For every Pydantic schema used by an agent we force `generate_structured()`
through both the primary AND fallback model named in `backend/config/models.yaml`:

    | schema                   | task     | primary                       | fallback                  |
    |--------------------------|----------|-------------------------------|---------------------------|
    | IntakeOutput             | intake   | openai/gpt-4o-mini            | anthropic/claude-haiku-4-5 |
    | PlannerOutput            | planner  | openai/gpt-4o                 | anthropic/claude-sonnet-4-5 |
    | AnalystStructuredOutput  | analyst  | anthropic/claude-sonnet-4-5   | openai/gpt-4o             |
    | CriticStructuredOutput   | critic   | anthropic/claude-sonnet-4-5   | openai/gpt-4o             |
    | VerifierStructuredOutput | verifier | openai/gpt-4o                 | google/gemini-2.5-pro     |
    | WriterReportPayload      | writer   | anthropic/claude-sonnet-4-5   | openai/gpt-4o             |

Each cell runs once with a minimal but realistic prompt and asserts the result
parses as the schema. On failure we re-raise the original exception so the
short-form pytest output carries `provider/model + schema + error_kind`,
matching the spec's "surface the exact provider + model + schema + error".

Tests skip cleanly if the relevant API key is unset (so PRs from forks stay
green); they fail loudly when the key is set and the round-trip fails.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from pydantic import BaseModel

from agents.intake import INTAKE_SYSTEM, IntakeOutput
from agents.planner import PLANNER_SYSTEM, PlannerOutput
from core.inference.structured import generate_structured
from models.agent_structured import (
    AnalystStructuredOutput,
    CriticStructuredOutput,
    VerifierStructuredOutput,
)
from models.report import WriterReportPayload


# ---------------------------------------------------------------------------
# Realistic-but-minimal user prompts. The system prompts come from production
# agent modules so we exercise the same schema constraints the pipeline does.
# ---------------------------------------------------------------------------

INTAKE_USER = (
    "Strategic question to analyse:\n"
    "Should our SaaS company expand to Germany or France first?\n\n"
    "Generate 6 intake questions covering goal/success metric, constraints, current state, "
    "stakeholders, risk tolerance, and asymmetric risks. Each question must be specific."
)

PLANNER_USER = (
    "Query: Should our SaaS company expand to Germany or France first?\n\n"
    "Context available:\nWe are a 40-person mid-market B2B SaaS. €15M ARR. Six months runway "
    "of expansion budget. Looking at EU market entry."
)

ANALYST_SYSTEM = (
    "You are the Analyst agent. Synthesise the research into 6+ key_claims tied to evidence "
    "ids, a specific recommendation, trade-offs covering both options, and named assumptions. "
    "Output ONLY valid JSON matching the AnalystStructuredOutput schema "
    "(recommendation, confidence, core_reasoning, key_reasons, key_claims, reasoning_slots, "
    "trade_offs, evidence_strength, assumptions)."
)
ANALYST_USER = (
    "Question: Germany vs France for SaaS expansion?\n"
    "Evidence catalog (3 items):\n"
    " - ev_a (firm-vetted): Germany Mittelstand has 1,500 mid-market accounts using competing tools.\n"
    " - ev_b (web): France enterprise market is 30% larger but procurement cycles run 9 months.\n"
    " - ev_c (web): Both markets show 18-22% YoY growth in B2B SaaS adoption.\n"
    "Produce a recommendation, six key_claims citing evidence_ids from {ev_a, ev_b, ev_c}, "
    "trade-offs for each option, and explicit assumptions."
)

CRITIC_SYSTEM = (
    "You are the Critic agent. Stress-test the analyst output. Produce overall_assessment, "
    "revision_instructions (target/severity/instruction), weak_points, counterarguments, "
    "missing_evidence, risks_missed, confidence_adjustment, and a verdict of accept|revise|reject. "
    "Output ONLY valid JSON matching the CriticStructuredOutput schema."
)
CRITIC_USER = (
    "Analyst output (summary): Recommends Germany first via Mittelstand pilot. Confidence Medium. "
    "Cites Mittelstand pull and shorter procurement cycles. Three key_claims, one trade_off entry "
    "for each option, no quantification of cost vs impact, no kill criteria.\n"
    "Stress-test it: name at least three weak_points and one revision_instruction."
)

VERIFIER_SYSTEM = (
    "You verify analyst claims against an evidence catalog. For each claim list which "
    "evidence_ids support it and a verdict of supported|weak|unsupported|overstates. "
    "Output ONLY valid JSON matching the VerifierStructuredOutput schema "
    "(claim_assessments, overall, gap_summary, suggested_searches, contradictions)."
)
VERIFIER_USER = (
    'Analysis: {"key_claims":[{"text":"Germany Mittelstand has strong demand","evidence_ids":["ev_a"]},'
    '{"text":"France market is 30% larger","evidence_ids":["ev_b"]},'
    '{"text":"Argentina has the best growth","evidence_ids":[]}],"recommendation":"Germany first"}\n'
    'Evidence catalog: [{"id":"ev_a","quote":"Germany Mittelstand has 1,500 mid-market accounts."},'
    '{"id":"ev_b","quote":"France enterprise market is 30% larger but cycles run 9 months."}]\n'
    "Produce a claim_assessment for every claim and an overall verdict."
)

WRITER_SYSTEM = (
    "You are the Writer agent. Synthesise the analysis + verification into a consulting-grade "
    "report. Output ONLY valid JSON matching the WriterReportPayload schema (recommendation, "
    "confidence_level, summary, key_reasons, risks, counterarguments, next_steps, sources, "
    "caveats, executive_insights with claim_ids, recommendation_claim_ids, key_risks_structured, "
    "decision_criteria, options_matrix, kill_criteria, what_would_change_our_mind, "
    "evidence_ledger_summary). Every claim_id used must exist in the analysis input."
)
WRITER_USER = (
    "Analysis (key_claims): "
    'c1=Germany Mittelstand demand is concrete; c2=France procurement is slower; '
    'c3=Both markets growing 18-22% YoY.\n'
    "Verifier verdicts: c1 supported, c2 supported, c3 weak.\n"
    "Sources: Mittelstand market report (firm-vetted document); EU SaaS adoption survey (web).\n"
    "Produce one specific recommendation that names a country and concrete first move "
    "(segment, region, timeline). recommendation_claim_ids must reference c1/c2/c3."
)


# ---------------------------------------------------------------------------
# Test matrix. Each entry: (schema, task_kind, system, user, model).
# Test id format: "<schema>__<provider>__<role>" so failures read e.g.
#   test_structured_round_trip[WriterReportPayload__anthropic__primary]
# ---------------------------------------------------------------------------


def _key_for(model: str) -> str:
    head = model.split("/", 1)[0]
    return {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        # litellm reads either GEMINI_API_KEY or GOOGLE_API_KEY for AI Studio.
        "gemini": "GEMINI_API_KEY",
        "google": "GEMINI_API_KEY",
    }[head]


def _provider_label(model: str) -> str:
    return model.split("/", 1)[0]


MATRIX: list[tuple[type[BaseModel], str, str, str, str, str]] = [
    # IntakeOutput — primary openai/gpt-4o-mini, fallback anthropic/claude-haiku-4-5
    (IntakeOutput, "intake", INTAKE_SYSTEM, INTAKE_USER, "openai/gpt-4o-mini", "primary"),
    (IntakeOutput, "intake", INTAKE_SYSTEM, INTAKE_USER, "anthropic/claude-haiku-4-5", "fallback"),
    # PlannerOutput — primary openai/gpt-4o, fallback anthropic/claude-sonnet-4-5
    (PlannerOutput, "planner", PLANNER_SYSTEM, PLANNER_USER, "openai/gpt-4o", "primary"),
    (PlannerOutput, "planner", PLANNER_SYSTEM, PLANNER_USER, "anthropic/claude-sonnet-4-5", "fallback"),
    # AnalystStructuredOutput — primary anthropic/claude-sonnet-4-5, fallback openai/gpt-4o
    (AnalystStructuredOutput, "analyst", ANALYST_SYSTEM, ANALYST_USER, "anthropic/claude-sonnet-4-5", "primary"),
    (AnalystStructuredOutput, "analyst", ANALYST_SYSTEM, ANALYST_USER, "openai/gpt-4o", "fallback"),
    # CriticStructuredOutput — primary anthropic/claude-sonnet-4-5, fallback openai/gpt-4o
    (CriticStructuredOutput, "critic", CRITIC_SYSTEM, CRITIC_USER, "anthropic/claude-sonnet-4-5", "primary"),
    (CriticStructuredOutput, "critic", CRITIC_SYSTEM, CRITIC_USER, "openai/gpt-4o", "fallback"),
    # VerifierStructuredOutput — primary openai/gpt-4o, fallback google/gemini-2.5-pro
    # (we use the YAML-canonical "google/" prefix so this test validates the
    # google/ → gemini/ rewrite in litellm_client._normalise_model_for_litellm).
    (VerifierStructuredOutput, "verifier", VERIFIER_SYSTEM, VERIFIER_USER, "openai/gpt-4o", "primary"),
    (VerifierStructuredOutput, "verifier", VERIFIER_SYSTEM, VERIFIER_USER, "google/gemini-2.5-pro", "fallback"),
    # WriterReportPayload — primary anthropic/claude-sonnet-4-5, fallback openai/gpt-4o
    (WriterReportPayload, "writer", WRITER_SYSTEM, WRITER_USER, "anthropic/claude-sonnet-4-5", "primary"),
    (WriterReportPayload, "writer", WRITER_SYSTEM, WRITER_USER, "openai/gpt-4o", "fallback"),
]


def _test_id(case: tuple[Any, ...]) -> str:
    schema_cls, _task, _sys, _usr, model, role = case
    return f"{schema_cls.__name__}__{_provider_label(model)}__{role}"


def _is_transient_upstream_error(exc: BaseException) -> bool:
    """Anthropic 529 (Overloaded), 5xx from any provider, and connection blips
    surface through litellm as APIConnectionError / ServiceUnavailableError /
    InternalServerError / APIError. We retry these once with backoff so the
    test isn't flaky against API capacity, but still fail fast on auth/schema
    errors (BadRequest, AuthenticationError, ValidationError, schema-repair
    exhaustion) which are real bugs and would not be helped by a retry.
    """
    msg = str(exc)
    name = type(exc).__name__
    transient_names = {
        "APIConnectionError",
        "ServiceUnavailableError",
        "InternalServerError",
        "Timeout",
        "TimeoutError",
        "APITimeoutError",
        "APIError",
    }
    if name in transient_names:
        return True
    # litellm sometimes wraps 5xx into a generic APIError; sniff the message.
    return any(token in msg for token in ("'529 ", "'503 ", "'502 ", "Overloaded", "Event loop is closed"))


@pytest.mark.parametrize("case", MATRIX, ids=[_test_id(c) for c in MATRIX])
async def test_structured_round_trip(case: tuple[Any, ...]) -> None:
    schema_cls, task_kind, system, user, model, role = case
    key_var = _key_for(model)
    if not os.getenv(key_var):
        pytest.skip(f"{key_var} not set — skipping {schema_cls.__name__} on {model}")

    last_exc: BaseException | None = None
    backoffs = [10.0, 30.0]  # two retries with widening sleep on transient blips
    for attempt in range(len(backoffs) + 1):
        try:
            obj, _meta = await generate_structured(
                schema_cls,
                task_kind=task_kind,
                system=system,
                user=user,
                model_override=model,
                max_schema_repairs=2,
                max_empty_retries=1,
            )
            assert isinstance(obj, schema_cls), (
                f"unexpected return type for {schema_cls.__name__} on {model}: "
                f"{type(obj).__name__}"
            )
            return
        except Exception as e:  # noqa: BLE001 — surface or retry, never swallow
            last_exc = e
            if attempt < len(backoffs) and _is_transient_upstream_error(e):
                await asyncio.sleep(backoffs[attempt])
                continue
            break

    # Spec: "surface the exact provider + model + schema + error".
    provider = _provider_label(model)
    raise AssertionError(
        f"structured round-trip FAILED  "
        f"provider={provider} model={model} task={task_kind} "
        f"schema={schema_cls.__name__} role={role} "
        f"error={type(last_exc).__name__}: {str(last_exc)[:300]}"
    ) from last_exc
