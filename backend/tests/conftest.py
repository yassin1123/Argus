"""Test bootstrap.

Loads the repo-root .env at session start so local `pytest` runs find
OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY without the developer
having to source the env first. CI keeps using GitHub Actions secrets, which
are already exported into the job environment, so load_dotenv() is a no-op
there (default override=False).
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=False)
