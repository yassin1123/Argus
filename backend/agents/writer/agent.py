"""Writer agent. Phase 2 / Week 7 / Day 1: pulled out of the
single-file ``agents/writer.py`` so the schema registry can live
alongside it (``agents/writer/schemas/``).

W7/D2: per-mode prompts moved into ``agents/writer/prompts/`` and
selected via :func:`get_writer_prompt`. The pre-W7 ``WRITER_SYSTEM``
constant is preserved as a re-export of ``GENERAL_WRITER_PROMPT`` for
backward compat — every callsite that imported it still works.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from core.inference.structured import generate_structured

from .prompts import GENERAL_WRITER_PROMPT, get_writer_prompt
from .schemas import GeneralReportPayload, WriterReportBase, get_writer_schema

# Backward-compat: pre-W7/D2 imports of ``WRITER_SYSTEM`` keep working,
# unchanged in behaviour for the general / market_entry / due_diligence
# / growth_strategy modes.
WRITER_SYSTEM = GENERAL_WRITER_PROMPT

if TYPE_CHECKING:
    from core.consulting_modes import ResolvedConsultingMode  # noqa: F401


class WriterAgent:
    async def run(
        self,
        query: str,
        analysis: dict,
        critique: dict,
        research: dict,
        prior_analysis: dict | None = None,
        verification: dict | None = None,
        *,
        reasoning_graph: dict | None = None,
        claim_support: list[dict] | None = None,
        repair_hint: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        resolved_mode: "ResolvedConsultingMode | None" = None,
    ) -> WriterReportBase:
        prior = ""
        if prior_analysis is not None:
            prior = f"""
First analyst draft (superseded by revision): {json.dumps(prior_analysis, indent=2)[:4000]}
"""
        ver = json.dumps(verification or {}, indent=2)[:6000]
        rg = json.dumps(reasoning_graph or {}, indent=2)[:6000]
        cs = json.dumps(claim_support or [], indent=2)[:6000]

        # Mode header surfaces display_name + description so the LLM
        # knows what kind of memo to write under (and the cover/header
        # references the firm-overridden label when one exists).
        mode_header = ""
        if resolved_mode is not None:
            mh_parts: list[str] = [
                f"Consulting mode: {resolved_mode.display_name} "
                f"(slug: {resolved_mode.name})"
            ]
            if (resolved_mode.description or "").strip():
                mh_parts.append(f"Mode description: {resolved_mode.description.strip()}")
            mode_header = "\n".join(mh_parts) + "\n\n"

        user_msg = f"""
{mode_header}Original query: {query}
Structured reasoning graph (canonical structure — align narrative to this): {rg}
Claim–support table (evidence vs assumption vs inference; use for honesty): {cs}
Revised analysis (use this as the primary analytical position): {json.dumps(analysis, indent=2)}
Critique: {json.dumps(critique, indent=2)}
Verifier output: {ver}
Research summary: {json.dumps(research, indent=2)[:2500]}
{prior}
In key_reasons and counterarguments, reflect verification verdicts (supported / weak / unsupported / overstates).
Split tone using claim_support support_type where helpful (direct_quote vs paraphrase vs inference vs assumption).
Respect nli_label / entailment fields in claim_support when present (contradicts / insufficient → flag honestly).
"""
        if repair_hint:
            user_msg += f"\n\nREPAIR REQUIRED:\n{repair_hint}\n"

        # W7/D2: registry-driven prompt selection. Built-in modes use
        # GENERAL_WRITER_PROMPT; m_and_a_diligence gets the strict
        # M&A-specific prompt that the W7/D1 schema validators back up.
        # Falls back to general for unknown / firm-defined slugs.
        if resolved_mode is not None:
            base_prompt = get_writer_prompt(resolved_mode.name)
        else:
            base_prompt = GENERAL_WRITER_PROMPT

        # Firm overlay (W6/D4) is appended after the per-mode prompt
        # so a firm can layer house style on top of the mode contract.
        system_prompt = base_prompt
        if resolved_mode is not None and (resolved_mode.writer_overlay or "").strip():
            system_prompt = (
                base_prompt
                + "\n\nFIRM WRITER OVERLAY:\n"
                + resolved_mode.writer_overlay.strip()
            )

        # W7/D1: registry-driven schema selection. Built-in modes still
        # validate against GeneralReportPayload; m_and_a_diligence gets
        # its bespoke class.
        schema_cls: type[WriterReportBase] = GeneralReportPayload
        if resolved_mode is not None:
            schema_cls = get_writer_schema(resolved_mode.name)

        out, _meta = await generate_structured(
            schema_cls,
            task_kind="writer",
            system=system_prompt,
            user=user_msg,
            temperature=0.3,
            session_id=session_id,
            trace_id=trace_id,
        )
        return out
