"""Legacy LLM helpers — now route through LiteLLM + record_llm_call.

Phase 7: kept for backward compat with agents that haven't migrated to
`completion_with_config`. Both paths now log to `llm_calls` for unified
cost tracking.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from openai import AsyncOpenAI

from core.inference.litellm_client import (
    chat_complete as _litellm_chat,
    estimate_cost,
    record_llm_call,
)
from core.model_router import resolve

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Direct OpenAI client — kept for embeddings + the few callers that need
    OpenAI-specific features. Chat completions should prefer `llm_call` below
    so they go through LiteLLM and the cost tracker."""
    global _client
    if _client is None:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = AsyncOpenAI(api_key=key)
    return _client


async def llm_call(
    system: str,
    user: str,
    model: str = "gpt-4o",
    temperature: float = 0.3,
    max_tokens: int = 4096,
    retries: int = 3,
    *,
    task_kind: str | None = None,
    session_id: str | None = None,
) -> str:
    """Single-shot LLM call via LiteLLM with cost tracking."""
    last_err: Exception | None = None
    for attempt in range(retries):
        t0 = time.perf_counter()
        try:
            response = await _litellm_chat(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                system=system,
                user=user,
                response_format=None,
                timeout_seconds=60.0,
            )
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            pt = getattr(usage, "prompt_tokens", None) if usage else None
            ct = getattr(usage, "completion_tokens", None) if usage else None
            total = (pt or 0) + (ct or 0)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.info("LLM call success model=%s tokens=%s", model, total)
            await record_llm_call(
                task_kind=task_kind or "ad_hoc",
                model=model,
                prompt_tokens=pt,
                completion_tokens=ct,
                latency_ms=elapsed_ms,
                usd_cost=estimate_cost(model, pt, ct),
                success=True,
                session_id=session_id,
            )
            return content
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning("LLM attempt %s failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                await asyncio.sleep(2**attempt)
    assert last_err is not None
    raise last_err


async def llm_call_for_task(
    task: str,
    system: str,
    user: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    session_id: str | None = None,
) -> str:
    """Resolve model/temperature/max_tokens from config/models.yaml for `task`."""
    cfg = resolve(task)
    return await llm_call(
        system,
        user,
        model=cfg.model,
        temperature=cfg.temperature if temperature is None else temperature,
        max_tokens=cfg.max_tokens if max_tokens is None else max_tokens,
        task_kind=task,
        session_id=session_id,
    )
