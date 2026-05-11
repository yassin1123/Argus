"""Writer agent. Phase 2 / Week 7 / Day 1: pulled out of the
single-file ``agents/writer.py`` so the schema registry can live
alongside it (``agents/writer/schemas/``).

W7/D2: per-mode prompts moved into ``agents/writer/prompts/`` and
selected via :func:`get_writer_prompt`. The pre-W7 ``WRITER_SYSTEM``
constant is preserved as a re-export of ``GENERAL_WRITER_PROMPT`` for
backward compat — every callsite that imported it still works.

W7/D3: schema validation failures surface with the schema class name
and the offending field path so a generic "Schema validation failed
after N repairs" becomes "MAndADiligenceReportPayload validation
failed at synergy_estimate.cost_synergies.0.basis_citations". The
underlying retry path inside ``generate_structured`` is unchanged —
we just unwrap its chained ``ValidationError`` and re-raise with a
mode-aware message.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import ValidationError

from core.inference.exceptions import InferenceSchemaError
from core.inference.structured import generate_structured

from .prompts import (
    GENERAL_WRITER_PROMPT,
    build_framework_instructions,
    get_writer_prompt,
)
from .schemas import GeneralReportPayload, WriterReportBase, get_writer_schema


class WriterSchemaValidationError(InferenceSchemaError):
    """Raised by :class:`WriterAgent` when ``generate_structured`` exhausts
    its repair retries on a schema mismatch. Carries the schema class
    name, the first offending field path, AND the last raw LLM
    response body (W7/D5 iterate) so callers can see exactly what the
    model emitted — truncation? markdown wrapper? freeform prose?
    The diagnosis matters because each shape needs a different fix.
    """

    def __init__(
        self,
        schema_name: str,
        field_path: str,
        original: BaseException,
        *,
        raw_text: str | None = None,
    ):
        super().__init__(
            f"{schema_name} validation failed at {field_path}",
            raw_text=raw_text,
        )
        self.schema_name = schema_name
        self.field_path = field_path
        self.__cause__ = original


def _format_field_path(loc: tuple) -> str:
    """Pretty-print a Pydantic ValidationError location tuple as
    ``a.b.0.c``-style dotted path for log messages.
    """
    parts: list[str] = []
    for x in loc:
        if isinstance(x, int):
            parts.append(str(x))
        else:
            parts.append(str(x))
    return ".".join(parts) if parts else "(root)"

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

        # W8/D4: framework instructions. Resolved-mode declares required +
        # optional frameworks; the writer prompt picks up matching
        # field-by-field guidance so the LLM knows which sub-payload
        # to fill at ``frameworks.<slot>``. Empty when the mode makes
        # no framework claim (most modes today).
        fw_cfg = getattr(resolved_mode, "frameworks", None) if resolved_mode is not None else None
        framework_block = build_framework_instructions(fw_cfg)
        if framework_block:
            system_prompt = system_prompt + "\n\nFRAMEWORK REQUIREMENTS:\n" + framework_block

        # W7/D1: registry-driven schema selection. Built-in modes still
        # validate against GeneralReportPayload; m_and_a_diligence gets
        # its bespoke class.
        schema_cls: type[WriterReportBase] = GeneralReportPayload
        if resolved_mode is not None:
            schema_cls = get_writer_schema(resolved_mode.name)

        # W7/D5 iterate: per-mode model-config overrides flow through
        # the layered modes system. ``max_tokens`` and ``model`` are
        # both plumbed into ``generate_structured`` (the latter as
        # ``model_override``, which the structured-output layer
        # forwards to the LLM client). Other params (temp, top_p)
        # can be added as kwargs land. ``max_tokens`` is bounded at
        # resolver-validation time to [256, 64000].
        gen_kwargs: dict[str, object] = {}
        if resolved_mode is not None:
            writer_overrides = (resolved_mode.model_overrides or {}).get("writer") or {}
            mt = writer_overrides.get("max_tokens")
            if isinstance(mt, int) and mt > 0:
                gen_kwargs["max_tokens"] = mt
            mo = writer_overrides.get("model")
            if isinstance(mo, str) and mo.strip():
                gen_kwargs["model_override"] = mo.strip()

        try:
            out, _meta = await generate_structured(
                schema_cls,
                task_kind="writer",
                system=system_prompt,
                user=user_msg,
                temperature=0.3,
                session_id=session_id,
                trace_id=trace_id,
                **gen_kwargs,
            )
        except InferenceSchemaError as ise:
            # generate_structured exhausted its repair retries.
            # Surface the offending field path + the raw LLM response
            # so logs / Sentry / the downstream operator see something
            # specific instead of the generic "Schema validation failed
            # after N repairs". The raw text distinguishes truncation
            # from markdown wrapping from freeform prose.
            raw = getattr(ise, "raw_text", None)
            cause = ise.__cause__
            if isinstance(cause, ValidationError):
                first = next(iter(cause.errors()), None)
                field_path = (
                    _format_field_path(first["loc"]) if first else "(unknown)"
                )
                raise WriterSchemaValidationError(
                    schema_name=schema_cls.__name__,
                    field_path=field_path,
                    original=cause,
                    raw_text=raw,
                ) from ise
            raise WriterSchemaValidationError(
                schema_name=schema_cls.__name__,
                field_path="(no validation error attached)",
                original=ise,
                raw_text=raw,
            ) from ise
        return out
