"""Public text/JSON completion APIs with timeout, optional fallback, usage logging."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from openai import RateLimitError

from core.inference.exceptions import InferenceTimeout
from core.inference.usage import log_inference_usage
from core.llm import get_client
from core.model_router import TaskModelConfig, resolve

logger = logging.getLogger(__name__)


async def _chat_create(
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    system: str,
    user: str,
    response_format: dict[str, str] | None,
    timeout_seconds: float,
) -> Any:
    client = get_client()

    async def _call() -> Any:
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
        return await client.chat.completions.create(**kwargs)

    return await asyncio.wait_for(_call(), timeout=timeout_seconds)


def _usage_from_response(resp: Any) -> tuple[int | None, int | None]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None, None
    pt = getattr(usage, "prompt_tokens", None)
    ct = getattr(usage, "completion_tokens", None)
    return pt, ct


async def completion_with_config(
    cfg: TaskModelConfig,
    *,
    system: str,
    user: str,
    task_kind: str,
    session_id: str | None = None,
    trace_id: str | None = None,
    response_format: dict[str, str] | None = None,
    temperature_override: float | None = None,
    max_tokens_override: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Single chat completion with timeout and one fallback model retry on timeout.
    Returns (assistant_text, meta) where meta includes model_used, prompt_tokens, completion_tokens, latency_ms.
    """
    temp = cfg.temperature if temperature_override is None else temperature_override
    mtok = cfg.max_tokens if max_tokens_override is None else max_tokens_override
    timeout = max(5.0, float(cfg.timeout_seconds))
    models_try = [cfg.model]
    if cfg.fallback_model and cfg.fallback_model != cfg.model:
        models_try.append(cfg.fallback_model)

    last_err: Exception | None = None
    for model in models_try:
        t0 = time.perf_counter()
        try:
            resp = await _chat_create(
                model=model,
                temperature=temp,
                max_tokens=mtok,
                system=system,
                user=user,
                response_format=response_format,
                timeout_seconds=timeout,
            )
            text = (resp.choices[0].message.content or "").strip()
            pt, ct = _usage_from_response(resp)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            log_inference_usage(
                task_kind=task_kind,
                model=model,
                latency_ms=elapsed_ms,
                session_id=session_id,
                trace_id=trace_id,
                prompt_tokens=pt,
                completion_tokens=ct,
            )
            meta = {
                "model_used": model,
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "latency_ms": elapsed_ms,
            }
            return text, meta
        except asyncio.TimeoutError as e:
            last_err = e
            logger.warning("Inference timeout task=%s model=%s; trying fallback", task_kind, model)
            if model == models_try[-1]:
                raise InferenceTimeout(f"task={task_kind} model={model}") from e
        except RateLimitError:
            raise
        except Exception as e:
            last_err = e
            logger.warning("Inference error task=%s model=%s: %s", task_kind, model, e)
            if model == models_try[-1]:
                raise
    assert last_err is not None
    raise last_err


async def generate_text(
    *,
    task_kind: str,
    system: str,
    user: str,
    session_id: str | None = None,
    trace_id: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> tuple[str, dict[str, Any]]:
    cfg = resolve(task_kind)
    return await completion_with_config(
        cfg,
        system=system,
        user=user,
        task_kind=task_kind,
        session_id=session_id,
        trace_id=trace_id,
        response_format=None,
        temperature_override=temperature,
        max_tokens_override=max_tokens,
    )


async def completion_json_object(
    *,
    task_kind: str,
    system: str,
    user: str,
    session_id: str | None = None,
    trace_id: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model_override: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """One JSON-object mode completion (used by structured loop)."""
    cfg = resolve(task_kind)
    if model_override:
        from dataclasses import replace

        cfg = replace(cfg, model=model_override)
    return await completion_with_config(
        cfg,
        system=system,
        user=user,
        task_kind=task_kind,
        session_id=session_id,
        trace_id=trace_id,
        response_format={"type": "json_object"},
        temperature_override=temperature,
        max_tokens_override=max_tokens,
    )
