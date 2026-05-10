"""Structured LLM outputs: JSON mode + Pydantic validation + failure-typed retries."""

from __future__ import annotations

import asyncio
import logging
import re
from enum import Enum
from typing import TypeVar

from openai import RateLimitError
from pydantic import BaseModel, ValidationError

from core.inference.exceptions import InferenceSchemaError, InferenceTimeout
from core.inference.generate import completion_json_object
from core.inference.repair import build_schema_repair_message, schema_excerpt
from core.model_router import resolve

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_FENCE_OPEN_RE = re.compile(r"^```(?:json)?\s*\n?", re.IGNORECASE)


def _extract_json_payload(text: str) -> str:
    """Strip markdown fences / prose preamble so model_validate_json can parse.

    OpenAI in ``response_format={"type":"json_object"}`` mode returns clean
    JSON, but Anthropic doesn't accept that kwarg in litellm 1.40.20 — so for
    Phase 1 cross-family routing we drop the kwarg on Anthropic in
    ``litellm_client.chat_complete`` and rely on the agent system prompts'
    "Output ONLY valid JSON" instruction. Claude usually obeys but occasionally
    wraps the JSON in a ```json ... ``` fence or a short prose preamble; this
    helper normalises both shapes back to a parseable object string.

    W7/D5 iterate: on long structured outputs (e.g. the M&A writer's
    7-section payload) Claude sometimes opens a ``` fence and never
    closes it because the response runs out of token budget mid-JSON.
    The original closed-only regex couldn't recover that case and fell
    through to a malformed `find("{") .. rfind("}")` span. We now
    handle the open-fence-no-close path explicitly: strip the leading
    fence and trim back to the outermost balanced object.
    """
    s = (text or "").strip()
    if not s:
        return s
    # Closed fence — preferred path.
    fence = _FENCE_RE.search(s)
    if fence:
        return fence.group(1).strip()
    # Open fence with no close (truncated response). Strip the opener
    # and continue with the body.
    open_only = _FENCE_OPEN_RE.match(s)
    if open_only:
        s = s[open_only.end():].strip()
    # Pure JSON: parse as-is.
    if s.startswith("{") and s.endswith("}"):
        return s
    # Mixed prose + JSON: trim to the outermost { ... } span.
    first = s.find("{")
    last = s.rfind("}")
    if first >= 0 and last > first:
        return s[first : last + 1]
    return s


class FailureKind(str, Enum):
    SCHEMA = "schema_validation"
    RATE_LIMIT = "rate_limit"
    EMPTY = "empty_response"
    API = "api_error"


async def generate_structured(
    model_cls: type[T],
    *,
    task_kind: str,
    system: str,
    user: str,
    max_schema_repairs: int = 2,
    max_empty_retries: int = 2,
    session_id: str | None = None,
    trace_id: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model_override: str | None = None,
) -> tuple[T, dict[str, object]]:
    """
    Call chat completions with JSON object mode, validate as `model_cls`.
    Returns (instance, meta) with model, task_kind, failure_retries, repair_notes.
    """
    cfg = resolve(task_kind)
    meta: dict[str, object] = {
        "model": cfg.model,
        "task_kind": task_kind,
        "failure_retries": 0,
        "repair_notes": [],
    }
    schema_hint = schema_excerpt(model_cls)
    repair: str | None = None
    schema_attempts = 0
    empty_attempts = 0
    max_attempts = max_schema_repairs + max_empty_retries + 4

    for attempt in range(max_attempts):
        try:
            user_content = user if not repair else f"{user}\n\n{repair}"
            text, call_meta = await completion_json_object(
                task_kind=task_kind,
                system=system,
                user=user_content,
                session_id=session_id,
                trace_id=trace_id,
                temperature=temperature,
                max_tokens=max_tokens,
                model_override=model_override,
            )
            meta["last_model_used"] = call_meta.get("model_used", cfg.model)
            if not text:
                empty_attempts += 1
                meta["failure_retries"] = int(meta["failure_retries"]) + 1  # type: ignore[arg-type]
                notes = list(meta["repair_notes"])  # type: ignore[arg-type]
                notes.append(FailureKind.EMPTY.value)
                meta["repair_notes"] = notes
                if empty_attempts > max_empty_retries:
                    raise InferenceSchemaError("generate_structured: empty response after retries")
                repair = "Return a single JSON object only; do not leave the message blank."
                await asyncio.sleep(0.35)
                continue

            try:
                obj = model_cls.model_validate_json(_extract_json_payload(text))
                return obj, meta
            except ValidationError as ve:
                schema_attempts += 1
                meta["failure_retries"] = int(meta["failure_retries"]) + 1  # type: ignore[arg-type]
                notes = list(meta["repair_notes"])  # type: ignore[arg-type]
                notes.append(f"{FailureKind.SCHEMA.value}:{ve.error_count()}")
                meta["repair_notes"] = notes
                logger.warning("Structured validation failed (%s/%s): %s", schema_attempts, max_schema_repairs, ve)
                # W7/D5 iterate: stash the last raw response on meta so
                # callers (e.g. WriterAgent) can surface it for forensic
                # inspection. Truncate aggressively — 4KB is enough to
                # see the failure mode (markdown? truncation? wrapper?)
                # without bloating logs.
                meta["last_raw_response"] = (text or "")[:4096]
                if schema_attempts > max_schema_repairs:
                    raise InferenceSchemaError(
                        f"Schema validation failed after {max_schema_repairs} repairs",
                        raw_text=(text or "")[:4096],
                    ) from ve
                repair = build_schema_repair_message(schema_hint, ve)
        except RateLimitError as e:
            notes = list(meta["repair_notes"])  # type: ignore[arg-type]
            notes.append(FailureKind.RATE_LIMIT.value)
            meta["repair_notes"] = notes
            wait = min(2 ** min(attempt, 5), 30)
            logger.warning("Rate limited; sleeping %ss: %s", wait, e)
            await asyncio.sleep(wait)
        except InferenceTimeout:
            raise
        except InferenceSchemaError:
            raise

    raise InferenceSchemaError("generate_structured: exhausted attempts")
