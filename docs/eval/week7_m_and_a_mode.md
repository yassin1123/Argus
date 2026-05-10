# Week 7 — M&A diligence mode end-to-end

**Status:** iterate

## Component check

| Component | Status | Evidence |
|---|---|---|
| Writer schema registry | ✅ | Day 1; 7 unit tests; backward-compat alias preserved |
| M&A diligence Pydantic schema | ✅ | Day 1; 7 nested types; strict validation |
| M&A mode in `consulting_modes.yaml` | ✅ | Day 2; resolver returns 6 branches + 6 reasoning slots + 4 source priorities + trust rules |
| M&A writer prompt | ✅ | Day 2; ~2.5KB; demands basis citations, dis-synergies, methodology per valuation point |
| Writer dispatcher (per-mode schema + prompt) | ✅ | Day 3; 4 dispatcher tests; `WriterSchemaValidationError` surfaces schema name + field path |
| Critic M&A-specific checks | ✅ | Day 3; 5 critic tests |
| Memo rendering for M&A shape | ✅ | Day 3; ValuationRangeTable + SynergyBreakdown + IntegrationTimeline + SchemaDriven fallback |
| Synthetic CIM | ✅ | Day 4; 13KB, 4 segments, 8 Q&As, 3 comparables |
| M&A integration test scaffold | ✅ | Day 4; gated `ARGUS_RUN_REAL_LLM_INTEGRATION=1` |
| **Run A produces a valid M&A payload end-to-end** | ❌ | Day 5 + iterate; root cause now hard-evidenced |
| **Layered `model_overrides` plumbing** | ✅ | Iterate addition; in resolver + writer; YAML override usable when the underlying model supports it |
| **Raw failed-attempt text capture** | ✅ | Iterate addition; persisted on `session.metadata.writer_schema_failure` for forensic inspection |

## End-to-end demo

**Brief (both runs, identical):**
> Conduct a diligence assessment of TargetCo Holdings, a UK industrial
> services group with £180m FY24 revenue. Quantify the deal opportunity,
> identify key risks, recommend deal structure and a valuation range.

Both runs in **Argus Demo Boutique** with the synthetic
**TargetCo Holdings — Project Lighthouse CIM** ingested.

### Structural divergence — top-level fields

| Field | Run A (M&A, last attempt) | Run B (Growth Strategy) |
|---|---|---|
| Mode dispatcher selected | `MAndADiligenceReportPayload` ✅ | `GeneralReportPayload` ✅ |
| Pipeline outcome | **`failed` at writer** (3 attempts, all 8192-token cap) | `complete` (writer succeeded after 1 retry) |
| `target_overview` | ❌ writer cut off mid-output | ❌ not in schema (correct) |
| `synergy_estimate` | ❌ writer cut off mid-output | ❌ not in schema (correct) |
| `valuation_range` | ❌ writer cut off mid-output | ❌ not in schema (correct) |
| `integration_plan` | ❌ writer cut off mid-output | ❌ not in schema (correct) |
| `deal_structure_implications` | ❌ writer cut off mid-output | ❌ not in schema (correct) |
| **Top-level field divergence count** | — | **0** (target was ≥5) |

The dispatcher correctly routed each engagement to its schema —
that part of the wedge fired. The runtime failure is downstream:
Run A's writer can't fit the M&A schema's required JSON within
Sonnet 4.5's hard 8192-token output cap.

### Run-level metrics

| Metric | Run A (M&A, latest attempt) | Run B (Growth Strategy) |
|---|---|---|
| Mode | `m_and_a_diligence` | `growth_strategy` |
| Pipeline state | `failed` (writer cap) | `deliverable_ready` |
| Writer ran successfully | ❌ no | ✅ yes (after 1 retry) |
| firm_library citations | 104 chunks | 72 chunks |
| Cost | $1.11 (single attempt) | $0.83 |
| Wall (s) | ~1148 (failed at writer) | ~870 |

### What did fire correctly

Three independent signals confirm the W7 architecture is sound:

1. **Mode dispatch reaches the writer.** Run A's writer was invoked
   with `MAndADiligenceReportPayload`; Run B's with
   `GeneralReportPayload`. The W7/D3 `WriterSchemaValidationError`
   surfaced for Run A with the schema class name and the `(root)`
   field path on every retry. (Confirmed in pipeline trace + new raw
   text capture on `session.metadata.writer_schema_failure`.)

2. **Schema strictness rejects bad output.** Every Run A attempt
   produced JSON that started parsing fine but ran out of content —
   Pydantic refused; orchestrator raised `WriterSchemaValidationError`
   on retry exhaustion.

3. **CIM consumed end-to-end.** Run A retrieved 104 firm_library
   chunks (CIM-anchored); Run B retrieved 72.

## The full diagnostic chain (iterate work)

The Day 5 wrap-up's first cut blamed token budget. The user's review
correctly pushed back: `failed at (root)` means Pydantic couldn't
even start parsing — that's consistent with truncation **but also**
with markdown wrappers or freeform prose. Three things were needed to
distinguish:

### Step 1 — capture the raw failed text

Added `raw_text` to `InferenceSchemaError` and to
`WriterSchemaValidationError`; the orchestrator's failure handler
now persists `session.metadata.writer_schema_failure.raw_text_excerpt`
(4KB cap) on any writer schema-exhaustion event. After this, every
failed attempt leaves a forensic trail that survives the
process. ([backend/core/inference/exceptions.py],
[backend/core/inference/structured.py],
[backend/agents/writer/agent.py],
[backend/agents/orchestrator.py])

### Step 2 — first re-run revealed markdown fences

The captured raw text on the next failed Run A started with
`` ```json ``. The LLM was wrapping its output in markdown code
fences. The existing `_FENCE_RE` regex required a *closed* fence
(both opening and closing `` ``` ``) — when the LLM ran out of token
budget mid-output, the closing fence was missing and the regex
fell through to a malformed substring extraction.

Fix landed:
- `_extract_json_payload` now also strips an *open-only* fence
  prefix when the closing fence is absent, then trims to the
  outermost balanced object.
  ([backend/core/inference/structured.py])
- M&A prompt explicitly forbids markdown wrappers ("Start your
  response with `{` and end with `}`. NO markdown code fences.").
  ([backend/agents/writer/prompts/_m_and_a.py])

### Step 3 — `max_tokens` override hit Anthropic 400

The user's review proposed bumping the writer's `max_tokens` to
16384 for the M&A mode specifically through the layered modes
system. Built that:
- New `model_overrides: dict[str, dict]` field on
  `ResolvedConsultingMode`, deep-merged like `trust_tier_rules`
  through firm + engagement layers.
  ([backend/core/consulting_modes/types.py],
  [backend/core/consulting_modes/resolver.py])
- `WriterAgent.run` reads `resolved_mode.model_overrides.writer.max_tokens`
  and threads it into `generate_structured`.
  ([backend/agents/writer/agent.py])
- Set `model_overrides.writer.max_tokens: 16384` on
  `m_and_a_diligence` in YAML.
  ([backend/config/consulting_modes.yaml])

Result: Anthropic returned **HTTP 400** for the writer call.
Sonnet 4.5's hard per-response cap is 8192 tokens by default;
going above requires the `extended-output-128k-2025-02-19` beta
header in the API request, which the current litellm client config
doesn't set. Override reverted (kept commented out for later).

### Step 4 — fence fix didn't help because the writer keeps hitting the 8192 cap

After dropping the override and re-running with the fence-strip fix
+ no-wrap prompt instruction, Run A failed AGAIN at `(root)`.
`llm_calls.completion_tokens` for all three writer attempts:
**8192, 8192, 8192** — every attempt maxed the model's per-response
budget exactly. The M&A schema is too long to fit a fully populated
payload in 8192 tokens regardless of fence handling.

(The captured raw text from this run still shows `` ```json `` —
the prompt instruction "no markdown fences" wasn't strong enough to
dissuade Claude. So the fence-strip code fix is the right bet on
that axis, not a prompt-only fix.)

## What works
- Resolver / schema / prompt / dispatcher / critic-checks /
  renderer — 39 unit tests across D1–D3 cover each layer
  independently
- Mode dispatcher routes the right schema + prompt to the writer
  for each engagement
- Schema strictness correctly rejects truncated/fence-wrapped
  output and `WriterSchemaValidationError` raises with the schema
  name and field path
- New layered `model_overrides` plumbing (iterate addition) is
  ready for any future config knob the M&A mode needs
- Raw failed-text capture is now a permanent forensic feature; any
  future writer-schema failure leaves a 4KB excerpt on
  `session.metadata.writer_schema_failure`

## What's still open (the iterate signal)

**One concrete fix between us and shipping Week 7**: enable extended
output for the writer task. Implementation options ranked:

1. **Wire `extended-output-128k-2025-02-19` beta header on Anthropic
   writer calls** in `core/inference/litellm_client.py`. Smallest
   change. After this, set `model_overrides.writer.max_tokens` to
   ~32k on the M&A mode and re-run. Estimated: 1-2 hours including
   re-test.

2. **Switch the writer model for `m_and_a_diligence`** to one whose
   default per-response cap fits the schema (e.g. some OpenAI
   models). Avoids the beta-header dependency but couples the
   wedge to a model swap. Same `model_overrides` mechanism, just
   `model: ...` instead of `max_tokens: ...`.

3. **Two-pass writer**: first pass produces base sections,
   second pass extends with the M&A-specific sections. Doubles
   cost per engagement but bounds per-call output and gives
   per-section retry granularity. Bigger refactor.

Other deferred items (smaller):
- M&A renderer not yet mounted in the workspace UI flow (D3
  ships components + tests; route/panel decision is Phase 4
  polish).
- `apply_mode_checks` not wired into the post-writer orchestrator
  path yet.

## Decision

- [ ] **Ship Week 7.** M&A mode produces a structurally distinct memo.
- [x] **Iterate.** One specific blocking issue:
  - Writer model output budget is 8192 tokens; M&A schema needs
    more. Wire Anthropic extended-output beta header
    (`core/inference/litellm_client.py`) and re-set the
    `model_overrides.writer.max_tokens` override on the M&A mode.
  - With that fix the same Run A demo should produce a valid
    `MAndADiligenceReportPayload` with the seven structural
    fields populated, and the headline assertion
    `structural_field_divergence_count >= 5` should pass on the
    next run.

The Week 7 wedge architecture is structurally complete (39 unit
tests + dispatcher correctness on a real run + raw-text capture
proves it). The remaining gap is **one config issue**: the writer
model's per-response output budget is too small for the schema we
designed, and going above the default needs a beta header that
isn't wired today. The iterate is small but load-bearing — exactly
matching the user's pre-iterate review call.

Run records:
- `backend/eval_runs/week7_e2e/A_m_and_a.json` (gitignored — last
  attempt's capture)
- `backend/eval_runs/week7_e2e/B_growth_strategy.json` (gitignored)
- `backend/eval_runs/week7_e2e/summary.json` (committed)
- W7/D4 single-shot integration capture:
  `backend/eval_runs/week7_d4_integration/`
- W7/D5 iterate-attempt logs: `w7d5_iterate*.log` (gitignored)
