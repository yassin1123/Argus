"""Phase 2 / Week 7 / Day 2 — writer prompt registry tests.

The prompt is the contract between the M&A mode config (Day 2) and
the schema validators (Day 1). These tests guard against accidental
prompt regressions: removing the basis-citations or dis-synergies
language would let the LLM produce schema-valid but
contractually-invalid M&A memos.
"""

from __future__ import annotations

from agents.writer.prompts import (
    GENERAL_WRITER_PROMPT,
    M_AND_A_WRITER_PROMPT,
    get_writer_prompt,
)


def test_writer_prompt_registry_returns_m_and_a_prompt_for_mode() -> None:
    assert get_writer_prompt("m_and_a_diligence") is M_AND_A_WRITER_PROMPT


def test_writer_prompt_registry_unknown_mode_falls_back_to_general() -> None:
    assert get_writer_prompt("does_not_exist_xyz") is GENERAL_WRITER_PROMPT
    assert get_writer_prompt("") is GENERAL_WRITER_PROMPT
    # Firm-defined modes that don't declare a prompt also fall back —
    # same behaviour as the schema registry.
    assert get_writer_prompt("boutique_pricing_review") is GENERAL_WRITER_PROMPT


def test_m_and_a_prompt_under_3200_chars() -> None:
    """Sanity guard against runaway prompt edits. Every M&A writer call
    pays this token cost; doubling the prompt doubles the per-engagement
    cost and the LLM's effective context budget.

    Cap evolved with each iterate run as the prompt's schema-alignment
    surface grew (the M&A schema is the strictest payload in the
    registry):
      W7/D2 ship:        2500 (initial)
      W7 iterate-2:      2750 (field enumeration + type/array discipline)
      W7 iterate-3:      3200 (claim-linking section)

    For reference the GENERAL_WRITER_PROMPT is ~6.2KB; M&A is still
    half that. Further growth still needs justification.
    """
    assert len(M_AND_A_WRITER_PROMPT) <= 3200, (
        f"M_AND_A_WRITER_PROMPT is {len(M_AND_A_WRITER_PROMPT)} chars; "
        "spec caps at 3200. Drop the lowest-leverage line, don't grow."
    )


def test_m_and_a_prompt_mentions_basis_citations_and_dissynergies() -> None:
    """String-match assertions to catch accidental prompt regressions
    on the two contract-load-bearing rules:

    1. Synergies must cite a basis (rejected by schema otherwise).
    2. Dis-synergies are not optional (every M&A produces them).

    If either of these strings disappears from the prompt, the LLM
    will start producing schema-valid-but-contractually-empty M&A
    output and the test fails immediately.
    """
    text = M_AND_A_WRITER_PROMPT.lower()
    assert "basis citations" in text or "basis citation" in text
    assert "dis-synergies" in text
    # And the four-tier recommendation discipline.
    assert "proceed" in text and "walk away" in text
    # And the mandate to look at the firm library.
    assert "firm_library" in text or "firm library" in text
