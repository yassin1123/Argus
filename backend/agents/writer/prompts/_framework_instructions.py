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
        "Populate frameworks.two_by_two — a 2x2 matrix. Required FLAT fields (do NOT nest "
        "under an 'axes' object): title (str ≥4 chars, e.g. 'TargetCo capability screen'); "
        "x_axis_label (str, the dimension, e.g. 'Strategic fit'); x_axis_low_label + "
        "x_axis_high_label (str, the pole names, e.g. 'Low' and 'High'); y_axis_label, "
        "y_axis_low_label, y_axis_high_label (same shape for the vertical axis); items "
        "(list of AT LEAST 4 and AT MOST 8 entries) where each item is {name, quadrant ∈ "
        "{bottom_left, bottom_right, top_left, top_right}, rationale ≥20 chars, "
        "evidence_citations (list of ≥1 claim_id from key_claims)}; interpretation "
        "(str ≥30 chars, the narrative reading of the cluster pattern). For M&A diligence "
        "default to x_axis_label='Strategic fit', y_axis_label='Deal complexity'. "
        "FEWER THAN 4 ITEMS PRODUCES AN UNUSABLE MATRIX — if you can only identify 2-3 items, "
        "you have not done enough analysis; mine the analyst's key_claims for additional "
        "tiles (target sub-options, segments, deal sub-themes, capability gaps) until you "
        "have 4-8 differentiated items. The schema validator REJECTS payloads with fewer "
        "than 4 items in this field."
    ),
    "porters_five_forces": (
        "Populate frameworks.porters_five_forces — this is REQUIRED, not optional. "
        "Omitting the frameworks block or leaving porters_five_forces null causes the "
        "post-writer critic check to fail this engagement with an error-severity "
        "finding. EXACT top-level keys: market_definition (str ≥10 chars — scope of "
        "'this market'); rivalry, supplier_power, buyer_power, substitute_threat, "
        "new_entrant_threat (each is a ForceAssessment object — see shape below); "
        "overall_attractiveness (literal: low|moderate|high); overall_rationale (str "
        "≥30 chars synthesising which forces dominate). Do NOT nest the five forces "
        "inside a 'forces' object. Each ForceAssessment = {intensity ∈ {low, moderate, "
        "high}, rationale (str ≥30 chars, quantified where possible), key_drivers "
        "(list of 2-6 short labels), evidence_citations (list of ≥1 claim_id from "
        "key_claims)}. You MUST emit this block in your output; the analyst's "
        "evidence supports it whenever a market-entry / growth-strategy brief is "
        "in scope — mine the key_claims for competitive structure, buyer/supplier "
        "concentration, switching costs, and entry barriers."
    ),
    "value_chain": (
        "Populate frameworks.value_chain — REQUIRED when this framework is in the "
        "mode's required list. Omitting it triggers an error-severity critic finding. "
        "EXACT top-level keys: business_context (str ≥20 chars — scope: BU, "
        "geography, segment); activities (list of ≥4 ValueChainActivity objects); "
        "overall_thesis (str ≥30 chars — synthesis). Each ValueChainActivity = "
        "{name (str), category ∈ {primary, support}, canonical_step ∈ "
        "{inbound_logistics, operations, outbound_logistics, marketing_and_sales, "
        "service, firm_infrastructure, hr_management, technology_development, "
        "procurement} — primary activities use the first five, support activities "
        "use the last four; assessment (str ≥30 chars), competitive_implication "
        "(str ≥10 chars), evidence_citations (list of ≥1 claim_id from key_claims)}."
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
