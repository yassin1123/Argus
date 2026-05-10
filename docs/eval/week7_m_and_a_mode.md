# Week 7 — M&A diligence mode end-to-end

**Status:** iterate (cap blocker resolved; prompt↔schema drift is the new blocker)

## Component check

| Component | Status | Evidence |
|---|---|---|
| Writer schema registry | ✅ | Day 1; 7 unit tests; backward-compat alias preserved |
| M&A diligence Pydantic schema | ✅ | Day 1; 7 nested types; strict validation |
| M&A mode in `consulting_modes.yaml` | ✅ | Day 2; resolver returns 6 branches + 6 reasoning slots + 4 source priorities + trust rules |
| M&A writer prompt | ⚠️ | Day 2 ships, but does not enumerate the 8 base WriterReportBase fields nor pin number-as-string formatting — see "What's still open" below |
| Writer dispatcher (per-mode schema + prompt) | ✅ | Day 3; 4 dispatcher tests; `WriterSchemaValidationError` surfaces schema name + field path |
| Critic M&A-specific checks | ✅ | Day 3; 5 critic tests |
| Memo rendering for M&A shape | ✅ | Day 3; ValuationRangeTable + SynergyBreakdown + IntegrationTimeline + SchemaDriven fallback |
| Synthetic CIM | ✅ | Day 4; 13KB, 4 segments, 8 Q&As, 3 comparables |
| M&A integration test scaffold | ✅ | Day 4; gated `ARGUS_RUN_REAL_LLM_INTEGRATION=1` |
| Layered `model_overrides` plumbing (`max_tokens` and `model`) | ✅ | Iterate; in resolver + writer; YAML override usable |
| Raw failed-attempt text capture | ✅ | Iterate; persisted on `session.metadata.writer_schema_failure` |
| `apply_mode_checks` wired post-writer (advisory, non-blocking) | ✅ | Iterate; orchestrator persists `mode_check_failures` on `session.metadata` |
| Minimal valid M&A payload fixture + 3 downstream tests (critic + renderer) | ✅ | Iterate; `tests/test_m_and_a_downstream.py` — 3/3 green |
| **Run A produces a valid M&A payload end-to-end** | ❌ | Iterate run still fails — failure mode shifted from truncation to prompt drift |

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

## What's still open (the iterate signal)

**One concrete fix between us and shipping Week 7**: realign the
M&A writer prompt with the M&A schema. Specifically:

1. **Enumerate the eight base WriterReportBase fields** the
   prompt has to emit alongside the M&A-specific sections —
   `recommendation`, `confidence_level`, `summary`, `key_reasons`,
   `risks`, `counterarguments`, `next_steps`, `sources`. Today
   the prompt names `recommendation` only; the rest are
   inherited from the base schema and the LLM doesn't know they're
   required.

2. **Pin number-as-string formatting** for percent / multiplier
   fields (`growth_rate`, `*_margin`, etc.) with a worked example
   in the prompt body. The schema reads `str` because consultants
   prefer `"8%"` and `"4.5x"` over bare floats; the prompt has to
   tell the LLM that.

3. **Pin array shape** for synergies, risks, and integration-plan
   dependencies. The schema reads `list[Synergy]`, the prompt
   has to explicitly say "arrays of objects, even when there's
   only one item."

4. **Enumerate the ~12 nested required fields** the latest run
   missed (or restructure them as optional-with-warning if the
   schema is over-specified relative to a real diligence memo).

After that one prompt rewrite, re-run the same e2e — the pivot
infrastructure already on this branch should let it land
without further code changes. Estimated: <2 hours of prompt
work + one e2e re-fire.

Other deferred items (smaller):
- M&A renderer not yet mounted in the workspace UI flow (D3
  ships components + tests; route/panel decision is Phase 4
  polish).

## Decision

- [ ] **Ship Week 7.** Run A still fails schema validation, so
  the headline assertion `headline_pass: true` does not hold.
  Per the iterate-spec rule "Don't ship if Step 5 produces
  anything other than headline_pass: true", we don't ship yet.
- [x] **Iterate (continued).** New, smaller, well-localised
  blocker: M&A writer prompt rewrite to match the schema (4
  bullet points above). The 8192-token cap problem is solved;
  the model swap works; the schema, dispatcher, critic checks,
  renderer, and fixture are all green. The remaining gap is
  prompt-level alignment — the cheapest possible
  iterate-to-ship path from here.

The Week 7 wedge architecture is structurally complete (76 unit
tests + dispatcher correctness on a real run + raw-text capture
+ model-override plumbing + post-writer mode checks all proven).
The prompt is the last thing standing between us and a clean
end-to-end M&A run. The iterate continues to be small and
load-bearing — exactly matching the user's pre-iterate review
call.

Run records:
- `backend/eval_runs/week7_e2e/A_m_and_a.json` (gitignored — last
  attempt's capture)
- `backend/eval_runs/week7_e2e/B_growth_strategy.json` (gitignored)
- `backend/eval_runs/week7_e2e/summary.json` (committed)
- W7/D4 single-shot integration capture:
  `backend/eval_runs/week7_d4_integration/`
- W7/D5 iterate-attempt logs: `w7d5_iterate*.log` (gitignored)
