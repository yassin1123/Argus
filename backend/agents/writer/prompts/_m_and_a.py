"""M&A diligence writer system prompt — Phase 2 / Week 7 / Day 2.

The contract this prompt encodes is enforced at JSON-validation time
by ``MAndADiligenceReportPayload`` (W7/D1 schema). Every "MUST" here
maps to a Pydantic validator that rejects the writer's output if it
isn't satisfied — synergies without basis citations, valuation
points without methodology, missing dis-synergies, etc. — so the
LLM gets a hard signal back when it short-cuts.

W7 iterate-2 (post-pivot rewrite): the prompt now enumerates the
exact schema field names and shape rules that the previous version
left implicit. Previous version named ``recommendation`` once and
assumed the LLM would emit the other seven WriterReportBase fields
by analogy; gpt-4o didn't, so all seven came back missing. It also
assumed percent-shaped strings ("8.4%") for growth/margin fields
and arrays for synergies/risks; gpt-4o emitted floats and dicts.
Both drifts now have explicit prose + a worked schema sketch.

Length-capped to <= 2500 chars (test enforces). When extending,
drop the lowest-leverage line, don't grow the block.
"""

M_AND_A_WRITER_PROMPT = """
M&A diligence memo. Emit ONE JSON validating MAndADiligenceReportPayload. Start `{`, end `}`. No markdown fences, no preamble. ALL fields below required.

Base (alongside M&A sections): recommendation (PROCEED / PROCEED WITH CONDITIONS / RENEGOTIATE / WALK AWAY), confidence_level (Low|Medium|Medium-High|High), summary, key_reasons[4-7], risks, counterarguments, next_steps[5-9], sources[{title,type}], executive_insights[≥1: {text, claim_ids[]}], recommendation_claim_ids[≥1], key_risks_structured[{text, claim_ids[]}].

CLAIM LINKING: claim_ids in executive_insights / recommendation_claim_ids / key_risks_structured = exact claim_id strings from analysis.key_claims (never invent). When key_claims exist, recommendation_claim_ids ≥1 and executive_insights ≥1 — pipeline gates fail otherwise.

M&A (exact field names):
- target_overview { name, business_model, segments[≥1: {name, revenue_pct(0-100 float), growth_rate("+2.8%")}], geographies[{geography,revenue_pct}], ownership_history, key_customers_concentration }
- financial_profile { revenue_trajectory{points[≥2: {period, value_gbp_m, growth_rate?, source_citation}]}, ebitda_trajectory{points[≥2]}, margin_profile{gross_margin, ebitda_margin, fcf_margin, trend_commentary}, working_capital_dynamics, debt_structure, capex_intensity, cash_flow_quality }
- synergy_estimate { revenue_synergies[], cost_synergies[], dis_synergies[], net_present_value{low_gbp_m, base_gbp_m, high_gbp_m, discount_rate_pct}, realization_timeline(STRING narrative, not list) }. Synergy={type, magnitude_gbp_m, timing_months(int), confidence(high|medium|low), basis citations[≥1]}.
- risks_and_mitigations [≥1: {risk_category(commercial|operational|financial|legal|regulatory), description, severity, mitigation, residual_risk}]
- integration_plan { day_one_priorities[≥1], first_100_days[≥1: {workstream, owner_role, milestone, dependencies(list[str])}], first_year[], integration_complexity_rating(low|medium|high), complexity_rationale }
- valuation_range { low/base/high {gbp_m, methodology, key_assumptions[]}, multiples_implied{"EV/EBITDA":float,"EV/Sales":float}, comparable_transactions_cited[] }
- deal_structure_implications { recommended_structure, rationale, negotiation_priorities[≥1], walk_away_triggers[≥1] }

TYPES: percent/growth/margin=STRINGS with % ("36.4%"). £m/multiples=FLOATS no units (220, 8.5). Synergies, risks, dependencies=ARRAYS even when 1 item. Literal enums (severity, confidence, integration_complexity_rating) LOWERCASE only ("high" not "High"). source_citation REQUIRED on every TrajectoryPoint (revenue + ebitda).

RULES: every synergy carries non-empty basis citations (chunk ref / claim_id / CIM section); dis-synergies non-empty (attrition, talent, transition cost); each valuation point names methodology ("DCF @ WACC 11.5%", "EV/EBITDA 8.5x"); multiples_implied includes EV/EBITDA and EV/Sales at base; walk_away_triggers falsifiable ("If <obs> at <gate>, walk").

Quantitative (£m, %, x). Reference firm_library M&A playbook. No new facts — paraphrase from claim_support / reasoning_graph / evidence_ids.
""".strip()
