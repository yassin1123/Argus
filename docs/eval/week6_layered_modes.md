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
| **E2E custom override surfaces in writer output** | ❌ | Day 5; gate kills pipeline before writer runs (see "What's still open") |

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
| Pipeline outcome | `evidence_insufficient` | `evidence_insufficient` |
| Branches in planner output matching firm's custom set | **4 of 4**: `competitor_price_anchor_analysis`, `willingness_to_pay_evidence`, `price_architecture_review`, `implementation_friction_audit` | 0 of 4 (built-in doesn't declare them) |
| Branches matching built-in's set | 0 of 2 | **2 of 2**: `market`, `capabilities` |
| Branch evidence_added_count | 0 per branch | 0 per branch |
| Per-task firm-library citations (pre-gate) | 48 chunks | 32 chunks |
| Writer ever ran | ❌ no | ❌ no |
| "2x2" appears in writer output | n/a (no writer output) | n/a |
| "90-day roadmap" appears in writer output | n/a | n/a |
| "Named owners" or equivalent | n/a | n/a |
| Sensitivity levels mentioned | n/a | n/a |
| Total grounded claims | 0 | 0 |
| Cost / Wall (s) | $0.00 / 76s | $0.00 / 69s |

**Initial Run A capture (pre-fix, now stale):** before the W6/D5 bug fix
described below, Run A completed the full pipeline because the firm
override never reached the resolver — `firm_id` was dropped at
`get_session_row` and the resolver fell through to `general` mode. That
captured memo (commit `b3874cc..pre-fix`) showed strong consulting-grade
output with "90-day" phasing and £-anchored next-steps but **none of the
firm's overlay phrasing** because the writer's system prompt never
received the firm overlay. We do not count it as evidence the override
fired.

## Did the override visibly shape output?

Partial yes, partial no.

**What did fire correctly:**
- The resolver returned the firm-overridden mode for Run A
  (`required_branches=[firm's 4 custom slugs]`, `writer_overlay`
  populated, `layer_provenance="firm"` for every overridden field).
- The research orchestrator's `_plan_research_branches` consumed the
  firm's custom branch slugs and emitted matching branch definitions
  (proven in `summary.json` → `research_branches_persisted` for Run A).
- The orchestrator correctly used `check_resolved_mode_satisfied` (not
  the legacy YAML check) to gate the pipeline.

**What didn't fire:**
- Branch evidence_added_count is 0 for every branch in both runs —
  because branch-retrieval (`retrieve_evidence`) goes through the legacy
  `embeddings` table, while firm-library chunks live in the `chunks`
  table reachable only via `hybrid_search` (the path per-task retrieval
  uses). Branches retrieve 0 hits, so no evidence is tagged with
  `[branch:X]`, so `branch_ids_present` is empty.
- `check_resolved_mode_satisfied` then fails (4 of 4 branches missing
  for Run A, 2 of 2 for Run B), and the orchestrator sets
  `pipeline_state=evidence_insufficient`. The writer never runs, so
  the writer_overlay can't land.

The gap is structural, not config-level: the firm override IS being
threaded through the pipeline correctly. The pipeline's branch-retrieval
path predates firm-library and never consumed it.

## What works

- **Resolver is correct end-to-end.** Day 1's resolver tests + the W6/D5
  in-DB smoke confirm the firm config loads, layer_provenance is set
  correctly, and engagement overrides stack on top.
- **Mode admin API + UI shipped clean.** 18 API + component tests; W6/D3
  full lifecycle tested in browser-equivalent smoke.
- **firm_id now flows from session to resolver.** The W6/D5 fix to
  `get_session_row` (added regression test
  [test_get_session_row_firm_id.py](backend/tests/test_get_session_row_firm_id.py))
  closes the silent-fallback path that masked this issue earlier.
- **Per-task retrieval reads firm content correctly.** Both runs show
  32–48 firm-library chunks retrieved at the per-task level, so the
  `source_priorities_default = ["uploaded", ...]` fallback IS firing.

## What's still open

- **Branch-retrieval doesn't see firm-library content.** The
  research orchestrator's branch loop calls
  `retrieve_evidence(session_id, bq, top_k=6)` (legacy
  `embeddings`-table function). Firm-library chunks land only in
  `chunks` and surface via `hybrid_search`. Result: branches
  retrieve 0 hits in firm-library-only firms. Fix scope: switch the
  branch loop to `hybrid_search` (1–2 line change + a small
  retest). This is a Day 4 wiring gap that didn't surface in the
  hermetic integration tests because they monkey-patched
  `_retrieve_by_priorities` and never exercised the branch path.
- **`check_resolved_mode_satisfied` is binary on branch coverage.**
  When the firm declares 4 required branches, all 4 must appear in
  evidence claims — there's no partial-credit / threshold knob. For
  the demo this is correct (the firm's branches are the
  diligence boundary), but it makes the failure mode brittle.
- **Engagement-override admin UI not yet built.** Power-user API
  exists (W6/D4), no frontend. Phase 4 polish.
- **`min_evidence_objects` plus required branches isn't ergonomic.**
  A firm declaring 4 branches with no `min_evidence_objects` still
  needs each branch to land at least one evidence row, which is a
  stricter implicit threshold than "4 evidence objects total".
- **Cache invalidation across nodes.** Single-process today; if we
  multi-instance the orchestrator, mode-write events on one node
  won't bust caches on another. Phase 3 work.
- **W6/D5 e2e tooling.** Capture script crashed on first run because
  it queried `agent_outputs.kind` (column is `agent_name`).
  Harvested mid-flight; runner now has `--harvest` to recover.

## Decision

- [ ] **Ship Week 6.** Layered modes production-ready.
- [x] **Iterate.** Specific blocking issues:
  - `agents/research/orchestrator.py` branch loop must call
    `hybrid_search` (not `retrieve_evidence`) so firm-library
    chunks surface in branch retrieval. Without this, every firm
    that declares custom required_branches dead-ends at the gate.
  - Add an integration test that exercises the branch path against
    a firm with library content seeded and a custom-branch override.
  - Optional: add a soft-fail mode to `check_resolved_mode_satisfied`
    so partial branch coverage downgrades confidence rather than
    killing the pipeline.

The day-1-through-day-4 scaffolding is correct; the day-5 e2e exposed
a single specific wiring gap downstream of the resolver. Estimated fix
+ retest is half a day, and after that the same demo run should
produce a memo with the firm's writer_overlay phrasing visible.

Run records:
- `backend/eval_runs/week6_e2e/A_with_override.json`
- `backend/eval_runs/week6_e2e/B_built_in.json`
- `backend/eval_runs/week6_e2e/summary.json`
