"""Demo-mode helpers. When DEMO_MODE=1, the stack runs without LLM keys and
serves fixture-backed agent output. Used by tests + the no-key demo seeder.
"""

from __future__ import annotations

import os


def is_demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "0").strip().lower() in ("1", "true", "yes", "on")


def has_openai_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())
