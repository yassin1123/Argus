# Week 6 — Layered consulting modes

**Status:** iterate

## Component check

| Component | Status | Evidence |
|---|---|---|
| Layered resolver + schema | ✅ | Day 1; 9 tests; merge semantics validated per truth table |
| Mode CRUD API | ✅ | Day 2; 9 API tests; cross-firm 404; audit on every mutation |
| Admin UI | ✅ | Day 3; 9 component tests; lifecycle smoke against real backend |
| Pipeline integration (planner / writer / critic / orchestrator) | ✅ | Day 4; 6 integration tests; 4 agents read resolved_mode |
| Engagement-level override API | ✅ | Day 4; `POST /api/sessions/{id}/mode_override` |
| **E2E custom override surfaces in writer output** | ❌ | Day 5; firm config flows through retrieval + 5 agents but verifier blocks the writer (see "What's still open") |

## End-to-end demo

**Substitution note:** The spec referenced ``growth_strategy_pricing`` as the
base_mode and Run B's mode. That built-in doesn't exist in
``backend/config/consulting_modes.yaml`` (only ``general``, ``market_entry``,
``due_diligence``, ``growth_strategy``). We used ``growth_strategy`` for both
the override's base_mode and Run B's no-override comparison.

**Brief (both runs):**
> Develop a pricing strategy for a UK retail business with 4 segments and
> £200M revenue. Identify price actions and an implementation roadmap.

### Run A — boutique_pricing_review (firm override)
### Run B — growth_strategy (built-in)

| Metric | Run A | Run B |
|---|---|---|
| Pipeline outcome | `evidence_insufficient` (post-verifier) | `evidence_insufficient` (post-research mode gate) |
| Pipeline depth reached | planner → research → analyst → critic → revise → critic-post → **verifier** → blocked | planner → research → blocked at mode gate |
| Branches in planner output matching firm's custom set | **4 of 4**: `competitor_price_anchor_analysis`, `willingness_to_pay_evidence`, `price_architecture_review`, `implementation_friction_audit` | 0 of 4 (built-in doesn't declare them) |
| Branches matching built-in's set | 0 of 2 | **2 of 2**: `market`, `capabilities` |
| firm_library chunks retrieved | **96** (vs 48 pre-fix) | 32 |
| LLM calls executed | 5 (analyst x2, critic x2, verifier) | 0 |
| Writer ever ran | ❌ no (verifier blocked) | ❌ no (mode gate blocked) |
| "2x2" appears in writer output | n/a | n/a |
| "90-day roadmap" appears in writer output | n/a | n/a |
| "Named owners" or equivalent | n/a | n/a |
| Sensitivity levels mentioned | n/a | n/a |
| Total grounded claims | 0 | 0 |
| Cost / Wall (s) | $0.41 / 522s | $0.00 / 69s |

## Day 5 fixes that landed

Two real bugs were caught and fixed during the e2e demo. Both are
checked in:

1. **`get_session_row` was dropping `firm_id`.** The orchestrator's
   `resolve_mode` at the top of `run_pipeline` was silently passing
   `firm_id=None`, falling back to legacy YAML, falling back to
   `general` mode. This had been masking the override layer entirely.
   Fix in [backend/db/queries.py](backend/db/queries.py); regression
   test at
   [backend/tests/test_get_session_row_firm_id.py](backend/tests/test_get_session_row_firm_id.py).

2. **Branch-retrieval used the legacy `embeddings`-table path.** The
   research orchestrator's branch loop called `retrieve_evidence`,
   which doesn't see firm-library chunks (those live in `chunks`,
   reachable only via `hybrid_search`). With the override active,
   branches retrieved 0 hits → no `[branch:X]` evidence → mode-gate
   tripped before the analyst ran. Fix in
   [backend/agents/research/orchestrator.py](backend/agents/research/orchestrator.py)
   line ~743; firm_library chunk count in Run A jumped from 48 to 96
   confirming the path now sees the right content.

After these fixes Run A runs **5 LLM calls deep** before stalling — a
substantive improvement over the pre-fix state (insufficient on the
mode gate before the analyst even fired).

## Did the override visibly shape output?

**Yes, in agent behaviour and retrieval; not in a final memo.**

What's verifiable from Run A:
- **Resolver returned the firm-overridden mode.** layer_provenance for
  every overridden field reads "firm". `required_branches` is the firm's
  custom set, `writer_overlay` and `planner_overlay` are populated.
- **Research orchestrator consumed the firm's branch slugs.** Run A's
  persisted `research_branches` show all 4 custom slugs verbatim
  (`competitor_price_anchor_analysis`, etc.); Run B's show only the
  built-in's `market` and `capabilities`.
- **Branch retrieval pulls firm-library content.** Run A's diversity
  shows `firm_library: 96` — twice Run B's `firm_library: 32` —
  because the firm's `source_priorities_default = ["uploaded", ...]`
  and the firm-library-aware branch retrieval surface Tesco / private-
  label / cohort-retention chunks for pricing-relevant questions.
- **Critic engaged with the overlay-implied structure.** The critic
  output includes the words "roadmap" and "owner" (proxy markers for
  the writer overlay's structural prescription) even though those
  appear in the **system prompt of the writer**, not the critic. This
  suggests the analyst's revised output picked up the pattern from
  the planner overlay propagating into the analytical structure.

What did NOT verify:
- **Writer never ran.** In Run A, the verifier deemed the analysis
  too thin (segment-specific revenue/margin/elasticity numbers
  absent — defensible call: the brief is hypothetical, the firm
  library has methodology not data). Pipeline tripped the
  post-verification `insufficient` gate ([orchestrator.py:938-963](backend/agents/orchestrator.py#L938-L963)).
- **Writer overlay phrasing ("2x2", "90-day roadmap", "named
  owners", "3 sensitivity levels") therefore appears in
  neither memo, because there is no memo.**

## What works

- **Resolver + cache + provenance: correct.** D1 truth-table tests,
  D2 API tests, D5 in-DB resolver smoke all green.
- **Mode admin path: shipped.** D2 API + D3 UI + D5 CLI seeder.
- **Agent prompt wiring: correct.** D4 integration tests prove the
  resolved mode reaches planner / writer / critic / research
  orchestrator; the firm overlays are appended to system prompts
  before LLM calls.
- **firm_id flows from session → resolver.** D5 fix +
  regression test.
- **Branch retrieval reads firm-library content.** D5 fix; Run A's
  `firm_library: 96` count proves it.
- **Per-task retrieval reads firm content correctly.** Both runs
  show 32–96 firm_library chunks, confirming source_priorities
  fallback is firing.

## What's still open

- **Verifier-discipline gate kills the writer when evidence is
  thin.** The post-verification `insufficient` gate fired on Run A
  because the verifier judged the analysis as having too many
  unsupported claims. This is correct discipline (the brief is
  hypothetical with no real data attached) but means the
  spec's "writer overlay shows up" assertion can't be tested
  with this brief shape. Two paths forward:
  - Re-run the demo with a brief that has uploaded data attached
    (a real CIM + market study). Closer to a production engagement
    shape; the verifier should accept the analysis.
  - Tune the verifier's pass threshold for hypothetical / planning
    briefs. Bigger work; out of D5 scope.
- **`check_resolved_mode_satisfied` is binary on branch coverage.**
  All required branches must appear in evidence claims. Soft-fail
  / partial-credit could let the pipeline continue with a confidence
  downgrade rather than hard-stopping.
- **Engagement-override admin UI not built.** Power-user API only.
- **Cache invalidation across nodes.** Single-process today;
  multi-instance needs a pub/sub channel.

## Decision

- [ ] **Ship Week 6.** Layered modes production-ready.
- [x] **Iterate.** Specific blocking issues:
  - Re-run the W6/D5 demo with a brief that has uploaded data
    attached, so the verifier accepts the analysis and the writer
    actually runs. Confirm the writer_overlay phrasing then lands
    in the final memo.
  - Optionally: add a soft-fail mode to
    `check_resolved_mode_satisfied` so partial branch coverage
    downgrades confidence rather than killing the pipeline.

The Day 5 e2e proved the layered-mode infrastructure works end-to-end
in agent behaviour and retrieval (Run A reached the verifier; Run B
stopped at the mode gate — different failure modes by design). What
it did NOT prove is that the writer_overlay phrasing reaches the
final memo, because the verifier blocked the writer in the only run
that got that far. That's the remaining gap before a clean ship.

Run records:
- `backend/eval_runs/week6_e2e/A_with_override.json`
- `backend/eval_runs/week6_e2e/B_built_in.json`
- `backend/eval_runs/week6_e2e/summary.json`
