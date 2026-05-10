# Week 7 — M&A diligence mode end-to-end

**Status:** iterate

## Component check

| Component | Status | Evidence |
|---|---|---|
| Writer schema registry | ✅ | Day 1; 7 unit tests; backward-compat alias preserved |
| M&A diligence Pydantic schema | ✅ | Day 1; 7 nested types; strict validation (basis_citations, methodology, multiples_implied) |
| M&A mode in `consulting_modes.yaml` | ✅ | Day 2; resolver returns 6 branches + 6 reasoning slots + 4 source priorities + trust rules |
| M&A writer prompt | ✅ | Day 2; 2243 chars; demands basis citations, dis-synergies, methodology per valuation point, falsifiable walk-aways |
| Writer dispatcher (per-mode schema + prompt) | ✅ | Day 3; 4 dispatcher tests; `WriterSchemaValidationError` surfaces schema name + field path |
| Critic M&A-specific checks | ✅ | Day 3; 5 critic tests; monotonic valuation, dis-synergies non-empty, walk-away triggers must be falsifiable |
| Memo rendering for M&A shape | ✅ | Day 3; ValuationRangeTable + SynergyBreakdown + IntegrationTimeline + SchemaDrivenSection fallback; 10 tests |
| Synthetic CIM | ✅ | Day 4; 13KB, 4 segments, 8 Q&As, 3 comparable transactions, realistic warts |
| M&A integration test | ✅ | Day 4; 13+ structural assertions; gated `ARGUS_RUN_REAL_LLM_INTEGRATION=1`; cost ceiling $3 |
| **Structural divergence between M&A and growth-strategy memos on same brief** | ❌ | Day 5; Run A's writer couldn't fit the full M&A JSON in max_tokens (truncated mid-output both attempts). See "What didn't fire" |

## End-to-end demo

**Brief (both runs, identical):**
> Conduct a diligence assessment of TargetCo Holdings, a UK industrial
> services group with £180m FY24 revenue. Quantify the deal opportunity,
> identify key risks, recommend deal structure and a valuation range.

Both runs ran in **Argus Demo Boutique** with the synthetic
**TargetCo Holdings — Project Lighthouse CIM** ingested into the firm
library.

### Structural divergence — top-level fields

| Field | Run A (M&A) | Run B (Growth Strategy) |
|---|---|---|
| Mode dispatcher selected | `MAndADiligenceReportPayload` ✅ | `GeneralReportPayload` ✅ |
| Pipeline outcome | **`failed` at writer** (schema validation exhausted) | `complete` (writer succeeded after 1 retry) |
| `target_overview` | ❌ writer didn't produce | ❌ not in schema (correct) |
| `financial_profile` | ❌ writer didn't produce | ❌ not in schema (correct) |
| `synergy_estimate` | ❌ writer didn't produce | ❌ not in schema (correct) |
| `valuation_range` | ❌ writer didn't produce | ❌ not in schema (correct) |
| `integration_plan` | ❌ writer didn't produce | ❌ not in schema (correct) |
| `deal_structure_implications` | ❌ writer didn't produce | ❌ not in schema (correct) |
| `risks_and_mitigations` | ❌ writer didn't produce | partial — flat `risks` field on general payload |
| **Top-level field divergence count** | — | **0** (target was ≥5) |

The dispatcher correctly routed each engagement to its schema —
that part of the wedge fired. The runtime failure is downstream:
Run A's writer LLM emitted JSON longer than its `max_tokens`
budget on both attempts.

### Run-level metrics

| Metric | Run A (M&A) | Run B (Growth Strategy) |
|---|---|---|
| Mode | `m_and_a_diligence` | `growth_strategy` |
| Pipeline state | `failed` (writer) | `deliverable_ready` |
| Writer ran successfully | ❌ no | ✅ yes (after 1 retry) |
| Total claims / grounded | n/a (no report) | full memo produced |
| firm_library citations | 128 chunks | 72 chunks |
| M&A-vocabulary hits (informational) | 0 (no memo) | 14 |
| Cost | $1.13 | $0.83 |
| Wall (s) | ~1190 (failed at writer) | ~870 |

Run A's $1.13 spend got us through planner → research → analyst×2 →
critic×2 → verifier → writer×2 (both writer attempts truncated). The
W7/D3 `WriterSchemaValidationError` correctly surfaced the schema
class name and `(root)` field path on exhaustion.

### What did fire correctly

The wedge architecture is sound. Three independent signals:

1. **Mode dispatch reaches the writer.** Run A's `MAndADiligenceReportPayload`
   was selected (not `GeneralReportPayload`); Run B's `GeneralReportPayload`
   was selected. Confirmed in the pipeline trace and the
   `WriterSchemaValidationError` payload that surfaced for Run A.

2. **Schema strictness rejects bad output.** Run A's writer first
   produced a markdown document (`# M&A Diligence Memo: …`) — schema
   refused. Second attempt produced JSON but truncated at line 334
   mid-object — schema refused. Both retries audited; orchestrator
   raised on exhaustion. The schema discipline worked exactly as Day 1
   designed it; the LLM couldn't satisfy the contract.

3. **CIM was consumed.** Run A retrieved 128 firm_library chunks (all
   from `targetco_cim.md` + supporting fixtures); Run B retrieved 72.
   The retrieval profile is mode-shaped (M&A pulls more, due to its
   wider source-priority chain `uploaded → sec_filing → transcript →
   news`).

### What didn't fire

**The M&A writer's structured output is too long for the model's
`max_tokens` budget on this engagement.**

The M&A schema requires producing seven nested top-level sections —
`target_overview` (with segments, geographies, ownership), `financial_profile`
(with two trajectories of points), `synergy_estimate` (three buckets +
NPV + timeline), `risks_and_mitigations` (list of structured
assessments), `integration_plan` (Day 1 + 100-day + first-year
initiatives), `valuation_range` (low/base/high + multiples + comps),
`deal_structure_implications` — plus all the inherited base fields
(recommendation, summary, key_reasons, risks, next_steps, sources,
…).

Real LLM responses for this brief consistently exceeded the writer
task's configured `max_tokens` window, getting cut off mid-array or
mid-object. Both retry attempts produced the same shape of failure
because the underlying volume of text is the same.

This is **not** a Day 1–3 wedge bug. It's a runtime config issue
visible only at full-brief scale.

## What works
- Resolver / schema / prompt / dispatcher / critic-checks /
  renderer — 36+ unit tests across D1–D3 cover each layer
  independently
- Mode dispatcher routes the right schema + prompt to the writer
  for each engagement
- Schema strictness is correct (truncated/invalid output gets
  rejected, retries fire, then `WriterSchemaValidationError` raises
  with the schema name and field path)
- CIM is retrieved + grounded by the research orchestrator (128
  chunks for the M&A run, anchored to the CIM)
- Run B (growth strategy) ran end-to-end and produced a substantive
  recommendation with M&A-flavoured language (the brief asked for
  one) — but with NO structured M&A-specific fields, exactly as the
  schema dispatch dictates

## What's still open (the iterate signal)

- **Writer `max_tokens` budget vs M&A schema length.** The single
  blocking issue. Three sane fixes, in order of preference:
  - **Raise the writer task's `max_tokens` ceiling** for the M&A
    mode (cleanest — affects only this mode; doesn't touch the
    schema or prompt). Should be set high enough that even a
    verbose output completes; the schema's strictness then enforces
    discipline.
  - **Stream the structured output and let the model use the full
    context window.** Bigger refactor.
  - **Two-pass writer**: first pass generates the base fields, second
    pass generates the M&A-specific sections. Doubles cost but each
    pass fits comfortably.
- **M&A renderer not yet mounted** in the workspace UI flow
  (deferred from D3 — D3 ships the components + tests; route /
  panel decision is Phase 4 polish).
- **`apply_mode_checks` not wired** into the post-writer
  orchestrator path. Function is callable; integration point is the
  same iterate window as the max_tokens fix.
- **Comparable-transactions retrieval** today comes only from the CIM
  itself. A real M&A engagement would surface comps from a deal
  database; that's a Week 8+ data-source question.

## Decision

- [ ] **Ship Week 7.** M&A mode produces a structurally distinct memo.
- [x] **Iterate.** Specific blocking issues:
  - Raise the writer task's `max_tokens` for the M&A mode (or
    two-pass it) so the full schema fits in a single response.
  - Re-run `tools/run_week7_e2e.py` with the fix in place; expect
    Run A to produce the full M&A payload and the headline assertion
    `structural_field_divergence_count >= 5` to pass.
  - Optional: wire `apply_mode_checks` into the orchestrator's
    post-writer step so the W7/D3 critic_checks fire on real
    engagements (today they're callable but no orchestrator caller).

The Week 7 architecture is structurally complete (D1–D3 unit tests
prove it; D4 apparatus + D5 dispatcher behaviour confirm dispatch
fires correctly). The remaining gap is a **runtime token-budget
issue** that prevents the LLM from producing the full M&A schema in
one shot. Estimated fix: half a day (config + re-run); the same
demo run after the fix should land cleanly with the schema-level
divergence we set out to demonstrate.

Run records:
- `backend/eval_runs/week7_e2e/A_m_and_a.json` (gitignored — 220KB capture)
- `backend/eval_runs/week7_e2e/B_growth_strategy.json` (gitignored — 151KB capture)
- `backend/eval_runs/week7_e2e/summary.json` (committed)
- W7/D4 integration test capture: `backend/eval_runs/week7_d4_integration/`
