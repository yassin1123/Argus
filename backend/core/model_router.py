"""Map logical task kinds to OpenAI models and generation params (YAML + env overrides)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"
_loaded: dict[str, Any] | None = None


@dataclass(frozen=True)
class TaskModelConfig:
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float = 120.0
    fallback_model: str | None = None
    structured_required: bool = False


def _load_yaml() -> dict[str, Any]:
    global _loaded
    if _loaded is not None:
        return _loaded
    if not _CONFIG_PATH.is_file():
        _loaded = {
            "default": {"model": "gpt-4o", "temperature": 0.3, "max_tokens": 4096},
            "tasks": {},
        }
        return _loaded
    with _CONFIG_PATH.open(encoding="utf-8") as f:
        _loaded = yaml.safe_load(f) or {}
    return _loaded


def resolve(task: str) -> TaskModelConfig:
    """Resolve model settings for a task key (e.g. planner, verifier)."""
    data = _load_yaml()
    default = data.get("default") or {}
    tasks = data.get("tasks") or {}
    row = {**default, **(tasks.get(task) or {})}

    env_key = f"ARGUS_MODEL_{task.upper()}"
    model = os.getenv(env_key, row.get("model", "gpt-4o"))
    temp_s = os.getenv(f"ARGUS_TEMP_{task.upper()}")
    temperature = float(temp_s) if temp_s is not None else float(row.get("temperature", 0.3))
    mt_s = os.getenv(f"ARGUS_MAX_TOKENS_{task.upper()}")
    max_tokens = int(mt_s) if mt_s is not None else int(row.get("max_tokens", 4096))

    to_s = os.getenv(f"ARGUS_TIMEOUT_{task.upper()}")
    timeout_seconds = float(to_s) if to_s is not None else float(row.get("timeout_seconds", 120))

    fb = os.getenv(f"ARGUS_FALLBACK_{task.upper()}")
    if fb is not None:
        fallback_model = fb.strip() or None
    else:
        fb_row = row.get("fallback_model")
        fallback_model = str(fb_row).strip() if fb_row else None
        if not fallback_model:
            fallback_model = None

    sr = row.get("structured_required", False)
    structured_required = bool(sr) if sr is not None else False

    return TaskModelConfig(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        fallback_model=fallback_model,
        structured_required=structured_required,
    )


def reload_config() -> None:
    """Test hook: force re-read of models.yaml."""
    global _loaded
    _loaded = None
