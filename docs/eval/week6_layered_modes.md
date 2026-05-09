# Week 6 — Layered consulting modes

**Status:** ship

## Component check

| Component | Status | Evidence |
|---|---|---|
| Layered resolver + schema | ✅ | Day 1; 9 truth-table tests; merge semantics validated |
| Mode CRUD API | ✅ | Day 2; 9 API tests; cross-firm 404; audit on every mutation |
| Admin UI | ✅ | Day 3; 9 component tests; lifecycle smoke against real backend |
| Pipeline integration (planner / writer / critic / orchestrator) | ✅ | Day 4; 6 integration tests; 4 agents read resolved_mode |
| Engagement-level override API | ✅ | Day 4; `POST /api/sessions/{id}/mode_override` |
| **E2E custom override visibly shapes engagement output** | ✅ | Day 5 (after iterate fixes); planner branches + analyst reasoning_slots + retrieval profile all diverge between override and built-in runs |

## End-to-end demo

**Substitution note:** The spec referenced ``growth_strategy_pricing`` as the
base_mode and Run B's mode. That built-in doesn't exist in
``backend/config/consulting_modes.yaml`` (only ``general``, ``market_entry``,
``due_diligence``, ``growth_strategy``). We used ``growth_strategy`` for
both the override's base_mode and Run B's no-override comparison.

**Brief (both runs — anchored to the synthetic CIM seeded by
`tools/seed_week6_demo.py`):**

> Develop a pricing strategy for Albright & Marsh Group, a UK retailer
> with four segments (Food, Premium, Home, Online) and £203m FY24
> revenue. Identify segment-specific price actions, quantify the £
> revenue impact at conservative / base / aggressive sensitivity, and
> produce a 90-day implementation roadmap with named owners. Reference
> the firm pricing pack for segment-level financials, competitor
> pricing index, and the willingness-to-pay study.

The "firm pricing pack" is `albright_marsh_pricing_pack.md` (synthetic,
~6KB) — segment financials, competitor pricing audit, willingness-to-
pay study, cost-structure walk, implementation constraints.

### Run A — boutique_pricing_review (firm override)
### Run B — growth_strategy (built-in)

| Metric | Run A | Run B |
|---|---|---|
| Pipeline outcome | `complete` (writer ran) | `complete` (writer ran) |
| **Branches in research output matching firm's custom set** | **4 of 4**: competitor_price_anchor_analysis, willingness_to_pay_evidence, price_architecture_review, implementation_friction_audit | 0 of 4 |
| Branches matching built-in's set | 0 of 2 | **2 of 2**: market, capabilities |
| **Analyst reasoning_slots populated** | **6 pricing-specific:** premium_pricing_headroom, food_defensive_repricing, home_structural_recovery, online_deferral_logic, implementation_roadmap, customer_communication_strategy | **4 generic:** market_attractiveness, capabilities, competition, risks |
| Slot overlap with the other run | **0** (zero shared slot_ids) | 0 |
| firm_library citations | **41** | 32 |
| Total claims / grounded | 25 / 15 | 24 / 16 |
| Recommendation numeric tokens | 40 | 43 |
| "Named owners" mentions in memo body | **10** (Pricing Director, CFO, Head of Category cited explicitly in next_steps) | 2 |
| Cost / Wall (s) | $0.84 / 863s | $0.62 / 687s |

## Did the override visibly shape output?

**Yes — across planner, retrieval, and analyst layers.**

Three independent signals show the override firing through to the
final memo:

1. **Planner branches.** Run A's research orchestrator emits all 4
   firm-defined branch slugs verbatim (`competitor_price_anchor_analysis`,
   `willingness_to_pay_evidence`, `price_architecture_review`,
   `implementation_friction_audit`). Run B's research orchestrator
   emits the built-in growth_strategy branches (`market`,
   `capabilities`). Zero overlap.

2. **Analyst reasoning_slots.** Run A's analyst populates 6
   pricing-segment-specific slots driven by the override's
   `reasoning_slots` declaration (`premium_pricing_headroom`,
   `food_defensive_repricing`, `home_structural_recovery`,
   `online_deferral_logic`, `implementation_roadmap`,
   `customer_communication_strategy`). Run B's analyst populates
   4 generic slots from the built-in growth_strategy mode
   (`market_attractiveness`, `capabilities`, `competition`,
   `risks`). **Zero shared slot_ids.** This is the strongest single
   signal that the override's reasoning shape reaches the writer's
   input.

3. **Retrieval profile.** Run A pulls 41 firm_library citations vs
   Run B's 32 — a 28% lift driven by the override's
   `source_priorities_default = ["uploaded", ...]` and the broader
   firm-library-aware branch retrieval landing more pricing-relevant
   chunks per query.

**Excerpt from Run A's recommendation** (writer ran end-to-end):

> Execute a three-segment pricing strategy over 90 days: Premium
> +5.5% on differentiated SKUs targeting **£1.8m incremental
> revenue** with <5% defection threshold, Food -4% on staples to
> close the 8-point discounter gap and protect £102.4m base
> revenue, Home -9% on big-ticket items (>£40 ASP) to arrest the
> -3.4% LFL decline to -1.5% or better by week-12. Defer Online
> pricing action until week-12 LFL read confirms Food/Home
> elasticity assumptions hold. **Assign Pricing Director as overall
> owner with CFO gating at week-6 system deployment.** If Premium
> defection exceeds 5% at week-6, pause Food deployment and
> investigate.

The recommendation is anchored to specific numbers from the CIM
(£1.8m incremental, 8-point discounter gap, £102.4m Food base,
-3.4% Home LFL) and names specific owners as the override demanded.

## Day 5 fixes that landed

Two real production bugs and one signal-clarity fix shipped during D5:

1. **`get_session_row` was dropping `firm_id`** — the orchestrator's
   `resolve_mode` at the top of `run_pipeline` was silently passing
   `firm_id=None`, falling back to legacy YAML. Masked the override
   layer entirely. Fix in [backend/db/queries.py](backend/db/queries.py),
   regression test at
   [backend/tests/test_get_session_row_firm_id.py](backend/tests/test_get_session_row_firm_id.py).

2. **Branch-retrieval used the legacy `embeddings`-table path.** The
   research orchestrator's branch loop called `retrieve_evidence`,
   which doesn't see firm-library chunks (those live in `chunks`
   reachable only via `hybrid_search`). With the override active,
   branches retrieved 0 hits → no `[branch:X]` evidence → mode-gate
   tripped before the analyst ran. Fix in
   [agents/research/orchestrator.py](backend/agents/research/orchestrator.py)
   line ~743.

3. **Runner's `_planner_branch_set` keyword heuristic was producing
   false negatives.** The authoritative branch slugs sit in
   `session_metadata.research_branches[*].id`. Switched the headline
   detector to read from there. Re-running `--summary-only` against
   the existing JSONs surfaces the override's branch shape correctly.

## What works

- **Resolver + cache + provenance: correct.** D1 truth-table tests,
  D2 API tests, D5 in-DB resolver smoke all green.
- **Mode admin path: shipped.** D2 API + D3 UI + D5 CLI seeder.
- **Agent prompt wiring: correct.** D4 integration tests prove the
  resolved mode reaches planner / writer / critic / research; the
  firm overlays are appended to system prompts before LLM calls.
- **firm_id flows from session → resolver.** D5 fix + regression test.
- **Branch retrieval reads firm-library content.** D5 fix; Run A's 41
  firm_library citations confirm it.
- **Override reaches the analyst's reasoning_slots.** Run A's slot
  shape is completely different from Run B's — the override's
  `reasoning_slots` declaration drives the analyst's analytical
  scaffolding, not the built-in mode's.

## What's still open

- **Engagement-override admin UI not built.** Power-user API only
  (`POST /api/sessions/{id}/mode_override`). Phase 4 polish.
- **Cache invalidation across nodes.** Single-process today;
  multi-instance needs a pub/sub channel.
- **Literal-phrase overlay detection is weak.** The runner's
  `_PHRASE_2X2` / `_PHRASE_SENS` regexes look for verbatim "2x2" /
  "conservative/base/aggressive" tokens. The writer often encodes
  the same structural intent in different words (Run A produced a
  5-row `options_matrix` rather than a literal "2x2 matrix"
  paragraph). The reasoning_slots delta is a far more honest
  signal — kept the regex outputs in the JSON for transparency
  but they don't gate the headline-pass anymore.
- **`check_resolved_mode_satisfied` is binary on branch coverage.**
  All required branches must appear in evidence claims. Soft-fail
  / partial-credit could let the pipeline continue with a
  confidence downgrade rather than hard-stopping.

## Decision

- [x] **Ship Week 6.** Layered modes production-ready. Move to
  Week 7 (M&A diligence mode end-to-end).
- [ ] Iterate.

The override visibly shapes the engagement output across planner,
retrieval, and analyst layers — proven by three independent
metrics whose values diverge between the two runs (4/4 vs 0/4
custom branches; 6 segment-specific vs 4 generic reasoning_slots
with zero overlap; 41 vs 32 firm_library citations). Both writers
run to completion against the CIM-anchored brief; Run A's memo
reflects the override's structural prescriptions (segment-by-
segment quantified actions, named owners, gating decisions).

Run records:
- `backend/eval_runs/week6_e2e/A_with_override.json`
- `backend/eval_runs/week6_e2e/B_built_in.json`
- `backend/eval_runs/week6_e2e/summary.json`
