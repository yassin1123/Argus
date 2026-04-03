"""Structured usage logging for inference calls."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("argus.inference")


def log_inference_usage(
    *,
    task_kind: str,
    model: str,
    latency_ms: float,
    session_id: str | None = None,
    trace_id: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    msg = (
        f"inference_usage task={task_kind} model={model} latency_ms={latency_ms:.1f} "
        f"prompt_tokens={prompt_tokens} completion_tokens={completion_tokens}"
    )
    log_ex: dict[str, Any] = {
        "task_kind": task_kind,
        "model": model,
        "latency_ms": round(latency_ms, 2),
    }
    if session_id:
        log_ex["session_id"] = session_id
    if trace_id:
        log_ex["trace_id"] = trace_id
    if extra:
        log_ex.update(extra)
    logger.info(msg, extra=log_ex)
