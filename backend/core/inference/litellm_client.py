"""LiteLLM call wrapper with cost tracking.

Phase 7: replaces direct OpenAI SDK usage so we can swap providers (Claude,
Gemini, Grok) by config in v1. For MVP only OpenAI is wired.

Every successful call writes a row to `llm_calls` so we can audit cost per
engagement, per user, per task.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import litellm
from litellm import acompletion

from db.connection import acquire

logger = logging.getLogger(__name__)

# Quiet down LiteLLM's noisy success-callback log lines in dev.
litellm.suppress_debug_info = True
# Don't drop unsupported params silently — we want to know if a model rejects something.
litellm.drop_params = False


async def chat_complete(
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    system: str,
    user: str,
    response_format: dict[str, str] | None,
    timeout_seconds: float,
) -> Any:
    """Single chat completion via LiteLLM. Returns the raw response object."""
    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    return await asyncio.wait_for(acompletion(**kwargs), timeout=timeout_seconds)


def _provider_for(model: str) -> str:
    """Best-effort provider tag for the cost-tracking row."""
    m = (model or "").lower()
    if m.startswith("claude") or m.startswith("anthropic/"):
        return "anthropic"
    if m.startswith("gemini") or m.startswith("vertex_ai/") or m.startswith("google/"):
        return "google"
    if m.startswith("grok") or m.startswith("xai/"):
        return "xai"
    return "openai"


def estimate_cost(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> float:
    """Best-effort USD cost via LiteLLM's pricing table; 0.0 if unknown."""
    pt = int(prompt_tokens or 0)
    ct = int(completion_tokens or 0)
    if pt + ct == 0:
        return 0.0
    try:
        # LiteLLM exposes cost_per_token(model, prompt_tokens=..., completion_tokens=...)
        from litellm import cost_per_token

        in_cost, out_cost = cost_per_token(model=model, prompt_tokens=pt, completion_tokens=ct)
        return float(in_cost) + float(out_cost)
    except Exception:
        return 0.0


async def record_llm_call(
    *,
    task_kind: str | None,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int,
    usd_cost: float,
    success: bool = True,
    error_kind: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Append a row to llm_calls. Best-effort — never raises."""
    try:
        async with acquire() as conn:
            await conn.execute(
                """
                INSERT INTO llm_calls
                  (session_id, user_id, task_kind, model, provider,
                   prompt_tokens, completion_tokens, total_tokens,
                   usd_cost, latency_ms, success, error_kind)
                VALUES
                  ($1::uuid, $2::uuid, $3, $4, $5,
                   $6, $7, $8, $9, $10, $11, $12)
                """,
                session_id,
                user_id,
                task_kind,
                model,
                _provider_for(model),
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                int((prompt_tokens or 0) + (completion_tokens or 0)),
                float(usd_cost or 0),
                int(latency_ms or 0),
                bool(success),
                error_kind,
            )
    except Exception as e:  # noqa: BLE001
        logger.debug("llm_calls insert skipped: %s", e)
