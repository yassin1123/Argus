"""Mode → writer system-prompt registry. W7/D2.

Mirrors the schema registry next door (``writer/schemas/_registry.py``):
mode slug -> system prompt. Built-in modes share
``GENERAL_WRITER_PROMPT`` until they get bespoke prompts;
``m_and_a_diligence`` ships with a strict prompt that the W7/D1 schema
validators back up.

Unknown slugs (firm-defined modes that don't declare a prompt) fall
back to ``GENERAL_WRITER_PROMPT``.
"""

from __future__ import annotations

from ._general import GENERAL_WRITER_PROMPT
from ._m_and_a import M_AND_A_WRITER_PROMPT

_PROMPT_REGISTRY: dict[str, str] = {
    "general": GENERAL_WRITER_PROMPT,
    "market_entry": GENERAL_WRITER_PROMPT,
    "due_diligence": GENERAL_WRITER_PROMPT,
    "growth_strategy": GENERAL_WRITER_PROMPT,
    "m_and_a_diligence": M_AND_A_WRITER_PROMPT,
}


def get_writer_prompt(mode_name: str) -> str:
    """Return the writer system prompt for ``mode_name``. Falls back to
    :data:`GENERAL_WRITER_PROMPT` for unknown slugs (including
    firm-defined modes without a custom prompt)."""
    return _PROMPT_REGISTRY.get(mode_name, GENERAL_WRITER_PROMPT)
