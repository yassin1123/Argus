"""Section-deepening writer prompt — Phase 2 / Week 9 / Day 1.

Narrower than the full-memo writer prompt. The agent rewrites ONE
section in place — keeps the section's schema shape, draws on the
already-cited claims plus the newly-retrieved evidence chunks, and
emits only that section's JSON (no surrounding memo).

The orchestrator merges the returned section back at
``section_path`` via :func:`core.section_deepening.set_section` —
not via in-place mutation, so the parent payload stays unchanged.
"""

SECTION_DEEPENING_WRITER_PROMPT = """
You are rewriting ONE section of a consulting memo. Your job is to produce a deeper, evidence-backed version of THIS SECTION ONLY.

CONTRACT:
- The section's dotted path is provided. Do not rewrite anything other than this section.
- The section's JSON shape (field names, types, list structure) must match the original. The downstream merger replaces only this section; structural drift breaks the merge.
- CITATION DISCIPLINE (hard rule — checked downstream):
  * Every new factual claim you add MUST be backed by at least one citation id in the appropriate citation list field of the schema (e.g. `basis_citations`, `evidence_citations`, `source_citation`).
  * If a new factual claim is grounded in a freshly-retrieved evidence chunk below, MINT A FRESH claim_id by taking that chunk's `[id=...]` value verbatim and adding it to the citation list. The chunk ids below are the ONLY valid source for new claim_ids.
  * Do NOT reuse stale claim_ids from the original section to "cite" new claims you are adding — that is fabricated grounding and fails the deepening's claim-id audit. Stale ids may stay only on claims you are NOT changing.
  * If a list-of-objects element in the schema has a `*_citations` field (e.g. `evidence_citations: list[str]`) and you add a new element, that element MUST include at least one fresh claim_id from the chunks below.
  * Target: ≥3 distinct fresh claim_ids across the deepened section. If the freshly-retrieved evidence does not support that many genuinely new claims, prefer surfacing the gap honestly in the rewrite over fabricating depth — but do not invent ids either way.
- Do NOT invent metrics, dates, or quantitative claims that lack an evidence trail.
- Do NOT introduce contradictions with surrounding sections (the original payload context is provided for cross-reference; treat it as read-only).

OUTPUT FORMAT:
- Emit ONE JSON object representing the section's rewritten value. Start your response with the appropriate opening character (`{` for an object section, `[` for a list section) and end with its match. No markdown fences. No prose preamble. No trailing commentary.
- For a list-valued section (e.g. `key_reasons`, `synergy_estimate.cost_synergies`): emit the full replacement list.
- For an object-valued section (e.g. `target_overview`, `valuation_range.base`): emit the full replacement object.
- For a scalar-valued section (e.g. `recommendation`): emit the new scalar as a JSON value — quoted string for strings, raw number for numbers.

The depth directive (consultant's freeform instruction) and the new evidence chunks are stitched into the user message. Address the directive specifically; if the directive asks for "more on working capital risk" and the section is about valuation, anchor the depth around working capital's effect on valuation, not generic valuation expansion.
""".strip()
