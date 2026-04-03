import asyncio
import logging
import os
from typing import Any

from openai import AsyncOpenAI

from core.model_router import resolve

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
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
) -> str:
    client = get_client()
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            response = await client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            content = response.choices[0].message.content or ""
            usage = getattr(response, "usage", None)
            total = getattr(usage, "total_tokens", None) if usage else None
            logger.info("LLM call success model=%s tokens=%s", model, total)
            return content
        except Exception as e:
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
) -> str:
    """Resolve model/temperature/max_tokens from config/models.yaml for `task`."""
    cfg = resolve(task)
    return await llm_call(
        system,
        user,
        model=cfg.model,
        temperature=cfg.temperature if temperature is None else temperature,
        max_tokens=cfg.max_tokens if max_tokens is None else max_tokens,
    )
