# Week 7 — M&A diligence mode end-to-end

**Status:** iterate (cap + prompt↔schema drift resolved; upstream pivot plumbed but not yet e2e-verified — re-tested under W8/D5 demo run, same upstream gate blocks; see [week8_frameworks.md](week8_frameworks.md) for the W8/D5 trajectory)

## Component check

| Component | Status | Evidence |
|---|---|---|
| Writer schema registry | ✅ | Day 1; 7 unit tests; backward-compat alias preserved |
| M&A diligence Pydantic schema | ✅ | Day 1; 7 nested types; strict validation |
| M&A mode in `consulting_modes.yaml` | ✅ | Day 2; resolver returns 6 branches + 6 reasoning slots + 4 source priorities + trust rules |
| M&A writer prompt | ✅ | Day 2 ship + iterate-2/3 rewrites: full schema field enumeration, type/array/literal discipline, claim-linking section. Char cap: 3200 (vs general's ~6.2KB). Trajectory: 39 schema errors → 8 → 0 across two iterate runs |
| Writer dispatcher (per-mode schema + prompt) | ✅ | Day 3; 4 dispatcher tests; `WriterSchemaValidationError` surfaces schema name + field path |
| Critic M&A-specific checks | ✅ | Day 3; 5 critic tests |
| Memo rendering for M&A shape | ✅ | Day 3; ValuationRangeTable + SynergyBreakdown + IntegrationTimeline + SchemaDriven fallback |
| Synthetic CIM | ✅ | Day 4; 13KB, 4 segments, 8 Q&As, 3 comparables |
| M&A integration test scaffold | ✅ | Day 4; gated `ARGUS_RUN_REAL_LLM_INTEGRATION=1` |
| Layered `model_overrides` plumbing (`max_tokens` and `model`) | ✅ | Iterate; in resolver + writer; YAML override usable |
| Raw failed-attempt text capture | ✅ | Iterate; persisted on `session.metadata.writer_schema_failure` |
| `apply_mode_checks` wired post-writer (advisory, non-blocking) | ✅ | Iterate; orchestrator persists `mode_check_failures` on `session.metadata` |
| Minimal valid M&A payload fixture + 3 downstream tests (critic + renderer) | ✅ | Iterate; `tests/test_m_and_a_downstream.py` — 3/3 green |
| **Run A produces a valid M&A payload end-to-end** | ❌ | Iterate runs progress through the failure stack — writer is now clean; failures sit upstream (analyst / critic JSON-truncation under 128-chunk evidence load). Still no full green pass. |

## End-to-end demo

**Brief (both runs, identical):**
> Conduct a diligence assessment of TargetCo Holdings, a UK industrial
> services group with £180m FY24 revenue. Quantify the deal opportunity,
> identify key risks, recommend deal structure and a valuation range.

Both runs in **Argus Demo Boutique** with the synthetic
**TargetCo Holdings — Project Lighthouse CIM** ingested.

### Latest iterate run (2026-05-10)

| Metric | Run A (M&A, OpenAI writer) | Run B (Growth Strategy) |
|---|---|---|
| Mode | `m_and_a_diligence` | `growth_strategy` |
| Pipeline state | `failed` (writer schema-validate exhaustion) | `deliverable_ready` |
| Writer ran successfully | ❌ no — schema mismatch | ✅ yes |
| Writer model used | `openai/gpt-4o` (per-mode override) | default Sonnet |
| firm_library citations | 128 chunks | 72 chunks |
| Cost | $0.97 (single attempt + 2 repairs) | $0.83 |
| Wall (s) | ~1006 | ~869 |
| `headline_pass` | **false** | n/a |

The dispatcher correctly routed each engagement to its schema —
that part of the wedge fired. Run B remains a clean control.

## What changed during iterate

The Day 5 wrap-up's first cut blamed token budget. The user's review
correctly pushed back: `failed at (root)` could mean truncation, but
also markdown wrappers or freeform prose. Six things landed during
iterate to stop guessing:

1. **Capture the raw failed text.** `InferenceSchemaError` and
   `WriterSchemaValidationError` now carry `raw_text`; the
   orchestrator's failure handler persists
   `session.metadata.writer_schema_failure.raw_text_excerpt` (4KB
   cap) on every writer schema-exhaustion event. Permanent forensic
   trail. ([backend/core/inference/exceptions.py](backend/core/inference/exceptions.py),
   [backend/core/inference/structured.py](backend/core/inference/structured.py),
   [backend/agents/writer/agent.py](backend/agents/writer/agent.py),
   [backend/agents/orchestrator.py](backend/agents/orchestrator.py))

2. **Open-only-fence stripping.** First captured raw text revealed
   Claude wrapping in `` ```json … `` and the closing fence was
   often missing because the response truncated. `_extract_json_payload`
   now strips an open-only fence prefix when no closing fence
   exists, and the M&A prompt explicitly forbids fences.
   ([backend/core/inference/structured.py](backend/core/inference/structured.py),
   [backend/agents/writer/prompts/_m_and_a.py](backend/agents/writer/prompts/_m_and_a.py))

3. **Layered `model_overrides` plumbing.** New
   `model_overrides: dict[task_kind, dict[str, Any]]` on
   `ResolvedConsultingMode`, deep-merged like `trust_tier_rules`
   through firm + engagement layers. `WriterAgent.run` reads
   both `max_tokens` and `model` overrides; `model_override`
   threads through `generate_structured` → `chat_complete`.
   Resolver validates `max_tokens ∈ [256, 64000]` and that
   `model` matches `provider/model`.
   ([backend/core/consulting_modes/types.py](backend/core/consulting_modes/types.py),
   [backend/core/consulting_modes/resolver.py](backend/core/consulting_modes/resolver.py),
   [backend/agents/writer/agent.py](backend/agents/writer/agent.py))

4. **Anthropic extended-output beta header — tried, reverted.**
   Wired `_extra_headers_for("anthropic/...")` to inject
   `extended-output-128k-2025-02-19` on every Anthropic call.
   Result: HTTP 400 at the FIRST Anthropic call (analyst, no LLM
   tokens consumed) — the beta name is rejected on Sonnet 4.5 today.
   Reverted; helper now returns `{}` for every provider. Pinned
   in `tests/test_litellm_client.py` so an accidental
   re-introduction shows up in CI.
   ([backend/core/inference/litellm_client.py](backend/core/inference/litellm_client.py),
   [backend/tests/test_litellm_client.py](backend/tests/test_litellm_client.py))

5. **Pivot rule: writer model swap to OpenAI for M&A.** Per the
   iterate-spec pivot rule, swapped to `openai/gpt-4o` via
   `model_overrides.writer.model` on the M&A mode (no `max_tokens`
   override; gpt-4o's per-response ceiling fits the schema).
   ([backend/config/consulting_modes.yaml](backend/config/consulting_modes.yaml))

6. **`apply_mode_checks` wired post-writer.** Advisory,
   non-blocking checks fire after the writer succeeds;
   `mode_check_failures` is merged into session metadata so
   reviewers see them even when the pipeline keeps moving.
   ([backend/agents/orchestrator.py](backend/agents/orchestrator.py))

7. **Minimal valid M&A payload fixture + 3 downstream tests.**
   Fully populated `MAndADiligenceReportPayload` with realistic
   TargetCo-shaped data; tests confirm critic + renderer paths
   are healthy independent of the LLM. Lets the LLM-side and
   schema-side problems be debugged separately.
   ([backend/tests/fixtures/m_and_a/__init__.py](backend/tests/fixtures/m_and_a/__init__.py),
   [backend/tests/test_m_and_a_downstream.py](backend/tests/test_m_and_a_downstream.py))

## What the latest run proved

The pivot worked at the level it was supposed to: gpt-4o produced a
complete JSON payload with all seven M&A sections present. No
truncation, no markdown wrappers. The 8192-token cap is no longer
the proximate cause of failure.

The new failure mode is **prompt↔schema drift** — Pydantic emitted
**39 validation errors** falling into four categories:

1. **Base WriterReportBase fields missing entirely.** The schema
   inherits `recommendation`, `confidence_level`, `summary`,
   `key_reasons`, `risks`, `counterarguments`, `next_steps`,
   `sources` from `WriterReportBase` (every mode produces these).
   The M&A prompt mentions only `recommendation` and never tells
   the LLM to emit the other seven base fields *alongside* the
   M&A-specific sections. gpt-4o emitted only the M&A-specific
   sections.

2. **Type drift: numbers vs strings.** Schema expects strings
   for percent-shaped fields (`growth_rate: "8%"`,
   `gross_margin: "35%"`). gpt-4o emitted bare floats (`8.0`,
   `35.0`). Pydantic refused to coerce.

3. **Shape drift: dict vs array.** Schema expects
   `synergy_estimate.{revenue,cost,dis}_synergies`,
   `risks_and_mitigations`, and `integration_plan.*.dependencies`
   as arrays of items. gpt-4o emitted single dicts / strings
   instead of arrays.

4. **Missing required nested fields.** ~12 nested required
   fields not emitted: `target_overview.{ownership_history,
   key_customers_concentration, business_model}`,
   `financial_profile.margin_profile.fcf_margin`,
   `valuation_range.{low,base,high}.gbp_m`,
   `valuation_range.multiples_implied`,
   `synergy_estimate.{net_present_value,realization_timeline}`,
   `integration_plan.{integration_complexity_rating,
   complexity_rationale}`, etc.

This is exactly the failure mode the iterate-spec was designed to
surface honestly — the user's pre-iterate review explicitly said
"failures are findings, not retry triggers." Logged here, not
papered over.

## What works (everything below the LLM)

- Resolver / schema / prompt-dispatcher / critic-checks /
  renderer / fixture — 76 unit tests across the writer + mode +
  resolver paths green (1 skipped — the LLM-integration scaffold).
- Mode dispatcher routes the right schema + prompt to the writer
  for each engagement; the M&A run took the M&A schema path
  end-to-end.
- Schema strictness correctly rejects shape-mismatched output;
  `WriterSchemaValidationError` carries schema name + first-error
  field path + 4KB raw-text excerpt.
- `model_overrides` plumbing for both `max_tokens` and `model`
  is in place and validates inputs.
- `apply_mode_checks` is wired and non-blocking — mode-specific
  invariants get logged on `session.metadata` even when the
  writer succeeds.
- Run B (Growth Strategy) is a clean control — the dispatcher and
  writer paths produce the right shape for non-M&A modes
  unchanged.

## Iterate-3 — prompt rewrite resolved the writer drift

The four-bullet prompt-rewrite plan landed. The realigned M&A
prompt now enumerates the full schema field set (base + M&A
sections), pins type discipline (strings for percent/margins,
floats for £m/multiples), pins array shape (synergies/risks/
dependencies always arrays), and includes a CLAIM LINKING
section that mirrors how the general prompt covers
`recommendation_claim_ids` / `executive_insights` /
`key_risks_structured`. Char cap on the prompt was bumped from
2500 → 2750 → 3200 across two iterate runs to make room; the
general prompt is ~6.2KB by comparison so 3.2KB is still tight.
([backend/agents/writer/prompts/_m_and_a.py](backend/agents/writer/prompts/_m_and_a.py),
[backend/tests/test_writer_prompts.py](backend/tests/test_writer_prompts.py))

Trajectory across the iterate runs:

| Run | Failure point | Result |
|---|---|---|
| Iterate-1 (post-pivot, original prompt) | Writer | **39** schema errors (base fields, types, shapes) |
| Iterate-2 (post-prompt-rewrite, retry-1) | Analyst | Transient JSON-truncation flake; writer never reached |
| Iterate-2 (retry-2) | Writer | **39 → 8** schema errors (enumeration worked) |
| Iterate-3 (post-tightening) | Writer | **8 → 0** schema errors. **But** caught by claim-linkage gate (`recommendation_claim_ids` / `executive_insights` empty → `evidence_insufficient` state) |
| Iterate-3 (post-claim-linking) | Critic | Transient JSON-truncation flake; writer never reached |

The writer's schema-alignment problem is solved: in the runs
where the writer was reached, output went from 39 → 8 → 0
schema errors as the prompt tightened.

## What's still open (the iterate signal)

**Upstream agent flakiness under 128-evidence load.** Two of
the three e2e re-fires this iterate failed before reaching the
writer: one at the analyst (Anthropic timeout → fallback returns
truncated JSON), one at the critic (3× retries all return
truncated JSON mid-list). The pattern is the same shape as the
original writer truncation that motivated the iterate's pivot —
LLM hits the 8192-token cap on a long structured payload. The
analyst and critic schemas also produce long structured outputs
when the firm library returns 128 chunks; the same fix surface
applies (per-task `model_overrides` + provider swap or extended-
output budget).

Iterate-4 landed the path-1 fix: analyst + critic now read
`model_overrides[task]` from the resolved mode (mirrors the writer's
W7 iterate-2 plumbing), the orchestrator passes `resolved_mode` to
all 9 analyst.run/.revise call sites and both critic.run sites, and
the M&A YAML now routes analyst, critic, and writer all to
`openai/gpt-4o`. ([backend/agents/analyst.py](backend/agents/analyst.py),
[backend/agents/critic.py](backend/agents/critic.py),
[backend/agents/orchestrator.py](backend/agents/orchestrator.py),
[backend/config/consulting_modes.yaml](backend/config/consulting_modes.yaml))

The pivot has not been verified end-to-end yet — committed as a
plumbing-only change after 90/90 unit tests green. Next session: one
e2e fire under M&A mode should now exercise the full pipeline on
gpt-4o and reach `deliverable_ready`.

Path 2 (input-volume trimming) remains a fallback if the pivot
under-performs:

- **Reduce the analyst/critic input volume.** 128 retrieved
  chunks is a lot; trimming to 64 (or applying max-marginal-
  relevance dedup before the agents) would also bring the
  structured outputs back inside the cap. Trades retrieval
  recall for output stability. Estimated: 2-4 hours.

Other deferred items (smaller):
- M&A renderer not yet mounted in the workspace UI flow (D3
  ships components + tests; route/panel decision is Phase 4
  polish).

## Decision

- [ ] **Ship Week 7.** No e2e run this iterate produced a clean
  M&A payload end-to-end. Per the iterate-spec rule "Don't ship
  if Step 5 produces anything other than headline_pass: true",
  we don't ship yet.
- [x] **Iterate (continued).** Writer prompt is now correct
  (39 → 0 schema errors when reached). Iterate-4 extends the
  same `model_overrides` pivot to analyst + critic; plumbing
  + YAML are committed and unit-tested but the pivot has not
  yet been verified by an e2e run that reaches the writer.
  Next session: one e2e fire to confirm.

The Week 7 wedge architecture is structurally complete (76 unit
tests + dispatcher correctness on a real run + raw-text capture
+ model-override plumbing + post-writer mode checks + minimal-
valid M&A payload fixture + claim-linkage prompt section all
proven). The work no longer sits at the writer; it sits one
layer up. Same plumbing, narrower scope.

Run records:
- `backend/eval_runs/week7_e2e/A_m_and_a.json` (gitignored — last
  attempt's capture)
- `backend/eval_runs/week7_e2e/B_growth_strategy.json` (gitignored)
- `backend/eval_runs/week7_e2e/summary.json` (committed)
- W7/D4 single-shot integration capture:
  `backend/eval_runs/week7_d4_integration/`
- W7/D5 iterate-attempt logs: `w7d5_iterate*.log` (gitignored)
