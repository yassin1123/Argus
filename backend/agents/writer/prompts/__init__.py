"""Per-mode writer system prompts. Phase 2 / Week 7 / Day 2."""

from ._general import GENERAL_WRITER_PROMPT  # noqa: F401
from ._m_and_a import M_AND_A_WRITER_PROMPT  # noqa: F401
from ._registry import _PROMPT_REGISTRY, get_writer_prompt  # noqa: F401
