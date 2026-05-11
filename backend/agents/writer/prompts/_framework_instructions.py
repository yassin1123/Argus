"""Per-framework writer prompt instructions — Phase 2 / Week 8 / Day 4.

When a resolved mode declares required or optional frameworks, the
writer agent stitches the matching instruction blocks into its system
prompt so the LLM knows exactly which JSON sub-payload to fill.

Auto-decide note (W8/D4 spec): exact wording + ordering are
auto-decided. Required frameworks come first (followed by the
"REQUIRED" tag), then optional ones (tagged "OPTIONAL — only if
your analysis genuinely supports it"). Both blocks reference the
``frameworks.<slot>`` JSON path explicitly so the LLM has no excuse
to emit the structure at the wrong location.

Size discipline: each block is kept ≤ 600 chars. With three blocks
possible (required + optional + optional) the total framework
addition tops out around 1.8KB — leaving the M&A writer prompt at
~4.3KB even when all three are loaded, well under the model context
budget.
"""

from __future__ import annotations

from core.consulting_modes import FrameworksModeConfig


# Per-slot instruction body. Keep each under ~600 chars; the LLM
# already has the field-shape information from the JSON schema —
# these blocks communicate intent + axis labels + counts.
_REQUIRED_INSTRUCTIONS: dict[str, str] = {
    "two_by_two": (
        "Populate frameworks.two_by_two — a 2x2 matrix. Pick two discriminating axes "
        "(for M&A diligence: 'Deal complexity' as the y-axis low→high, 'Strategic fit' "
        "as the x-axis low→high). Place 4-8 items from your analysis (target capabilities, "
        "sub-options, segments) in the four quadrants (bottom_left, bottom_right, "
        "top_left, top_right). Every item needs ≥1 evidence_citations from key_claims. "
        "End with an interpretation paragraph reading the cluster pattern."
    ),
    "porters_five_forces": (
        "Populate frameworks.porters_five_forces — define the market scope clearly "
        "(market_definition), then assess each of the five forces (rivalry, "
        "supplier_power, buyer_power, substitute_threat, new_entrant_threat). For each: "
        "intensity (low|moderate|high), a quantified rationale, 2-6 key_drivers, ≥1 "
        "evidence_citations from key_claims. Close with overall_attractiveness + "
        "overall_rationale synthesising which forces dominate."
    ),
    "value_chain": (
        "Populate frameworks.value_chain — set business_context (scope), then list ≥4 "
        "activities across primary (inbound_logistics, operations, outbound_logistics, "
        "marketing_and_sales, service) and support (firm_infrastructure, hr_management, "
        "technology_development, procurement). Each activity needs assessment + "
        "competitive_implication + ≥1 evidence_citations. Close with overall_thesis "
        "naming the strategic wins and gaps across activities."
    ),
}


_OPTIONAL_HEADER = (
    "OPTIONAL FRAMEWORKS — only populate these if your analysis genuinely supports "
    "them; otherwise leave the field null. Half-populated frameworks are worse than "
    "absent ones."
)


def build_framework_instructions(
    mode_config: FrameworksModeConfig | None,
) -> str:
    """Compose the framework-instruction block for a writer system prompt.

    Returns an empty string when the mode has no framework opinion
    (``mode_config is None`` or both lists empty). The caller can
    concatenate the returned string directly into the prompt — empty
    string disappears cleanly.

    Ordering: required first (so the LLM sees them earliest), then
    optional under a discouraging header that names the
    "half-populated = worse than absent" rule explicitly.
    """
    if mode_config is None:
        return ""
    if not mode_config.required and not mode_config.optional:
        return ""

    lines: list[str] = []

    if mode_config.required:
        lines.append("REQUIRED FRAMEWORKS — your output MUST include each of these:")
        for slot in mode_config.required:
            body = _REQUIRED_INSTRUCTIONS.get(slot)
            if body:
                lines.append(f"- {body}")

    if mode_config.optional:
        if lines:
            lines.append("")
        lines.append(_OPTIONAL_HEADER)
        for slot in mode_config.optional:
            body = _REQUIRED_INSTRUCTIONS.get(slot)
            if body:
                lines.append(f"- {body}")

    return "\n".join(lines).strip()
