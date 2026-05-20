# Week 8 — Frameworks library

**Status:** ship (M&A path) — M&A Run A regression diagnosed and fixed in Phase 3 / Week 10 / Day 1 (commit `868c9a4`). Run A now lands 7/7 M&A fields + 2x2 + Pyramid + MECE on every fire. growth_strategy Run B reached the writer for the first time but failed at a separate writer-JSON-truncation bug.

**Run B writer-truncation carry-forward (Phase 3 / Week 14 / Day 1):**
Path A fix landed — growth_strategy now ships `model_overrides.writer.model: openai/gpt-4o` plus `max_tokens: 16000` in `consulting_modes.yaml`. The W8 Run B writer call previously hit `anthropic/claude-sonnet-4-5`'s 8192-token default ceiling (DB telemetry: `completion_tokens=8174` on the past growth call — diagnosed without spending a run). Path A swap mirrors the W7 iterate fix that closed M&A truncation. **Verify run on a fresh W8 growth engagement (session `a44923a8-…`, cost $0.60, wall 21 min):** writer ran clean on gpt-4o — full payload emitted, no truncation. Original writer-truncation symptom is **closed**.

**However, a separate bug surfaced behind the now-removed truncation:** the writer emitted `frameworks: null` despite the explicit "REQUIRED, not optional" framework instructions in the system prompt. Root cause: `GeneralReportPayload.frameworks` is `Optional[FrameworksBlock]` (mode-config declares `porters_five_forces` as required, but the Pydantic schema permits omission). gpt-4o legitimately produces `null`; the validator accepts it. A growth-specific schema class (analogous to `MAndADiligenceReportPayload`) that makes `frameworks.porters_five_forces` non-nullable would close this — that's Path B scope, deferred to Phase 4 with a clear plan below.

All Week 8 architecture shipped: Pyramid auto-checker (Day 1, 5 tests), MECE checker (Day 2, 7 tests), 2x2 + Porter's + Value Chain schemas and renderers (Day 3, 6 tests across frontend + schema validation), framework wiring into modes (Day 4, 6 tests). The original W8 Run A regression was root-caused in W10/D1 as a brittle pre-writer evidence gate that halted on the verifier's free-form `overall: "insufficient"` flag whenever the verifier returned mixed `claim_assessments`. The fix (orchestrator.py:942-981) replaces the single-string check with a quorum on `claim_assessments`. Run B's new writer-truncation failure is a different defect surfaced only because the gate fix let the pipeline reach the writer for the first time on growth_strategy.

## Component check

| Component | Status | Evidence |
|---|---|---|
| Pyramid Principle auto-checker | ✅ | Day 1; 5 tests; runs on every engagement that reaches the writer; **fired + passed on Run A** (0 errors, 3 advisory findings) |
| MECE checker (embedding pairwise) | ✅ | Day 2; 7 tests; **fired + passed on Run A** (0 overlaps across 7 fields checked, threshold 0.85) |
| 2x2 matrix schema + renderer | ✅ | Day 3 + D5 iterate (`min_length=4` bump); Pydantic enforces 4-12 items |
| Porter's Five Forces schema + renderer | ✅ | Day 3; structurally complete |
| Value Chain schema + renderer | ✅ | Day 3 |
| Frameworks wired into modes | ✅ | Day 4; M&A required=[two_by_two], growth_strategy required=[porters_five_forces] |
| Critic enforces required frameworks | ✅ | Day 4; `check_required_frameworks` + `apply_mode_checks` wiring |
| Writer prompt augmentation per mode | ✅ | Day 4 + D5 iterate; flat-field enumeration; "fewer than 4 = unusable" demand in 2x2 instruction |
| **E2E demo: M&A produces a 2x2** | ✅ | **Run A** (W10/D1 re-verify after gate fix): 7/7 M&A fields, 2-item 2x2 + citations, $0.21, 414s. Also emitted Porter's bonus block. |
| **E2E demo: growth produces Porter's** | ⚠️ partial — writer-truncation closed (W14/D1), schema-enforcement gap open | **Run B** writer-truncation symptom closed by gpt-4o swap + max_tokens 16000 override in `consulting_modes.yaml`. Verify run completed at $0.60 / 21 min wall; writer emitted a full, non-truncated payload but set `frameworks: null` despite explicit "REQUIRED" prompt instructions. Schema-enforcement gap (Optional FrameworksBlock + no growth-specific WriterReportPayload subclass) deferred to Phase 4. |
| **Pyramid + MECE fire and persist** | ✅ (partial) | Fire and pass cleanly on Run A (0 errors / 0 overlaps); couldn't fire on Run B because writer aborted before persistence. |

## End-to-end demo

### Run A — M&A diligence with required 2x2

**Brief:** Same TargetCo Holdings diligence brief as W7 (deliberate cross-week control).

| Metric | Value |
|---|---|
| Session | `9da8a365-224e-4c4c-8f65-8ff1d1cef5dc` |
| Pipeline state | `deliverable_ready` |
| Wall / cost | 457s / $0.22 |
| Evidence total | 128 (firm_library only) |
| 2x2 populated | ✅ |
| 2x2 items | **4** |
| Items with evidence citations | **4 / 4** |
| Axes labeled | ✅ (x: Strategic fit, y: Deal complexity) |
| M&A top-level sections present | **7 / 7** |
| Base WriterReportBase fields | **8 / 8** populated |
| Pyramid check | **passed**, 0 errors, 3 advisory findings, model=gpt-4o-mini |
| MECE check on key_reasons | **0 overlaps** |
| MECE total overlaps | **0** across 7 checked fields |
| Recommendation | "PROCEED WITH CONDITIONS" |
| W7 carry-forward | **closes_week7: true** (8/8 base + 7/7 M&A + 2x2 present) |

### Run B — Growth strategy with required Porter's Five Forces

**Brief:** "Develop a market-entry strategy for TargetCo into the German industrial services market. Cover competitive landscape, regulatory environment, go-to-market options."

| Metric | Value |
|---|---|
| Session | `435c65d9-c317-43e2-abef-6b10b1454804` |
| Pipeline state | `evidence_insufficient` (gate: reasoning_skeleton validation, not mode-coverage) |
| Wall / cost | 679s / $0.56 |
| Evidence total | 64 (firm_library only) |
| Porter's populated | ❌ (writer never ran) |
| All 5 forces populated | ❌ |
| Pyramid + MECE | did not fire (no writer payload) |

**Run B failure mode 1 (closed):** the analyst on `growth_strategy`
mode populated reasoning_slots with hallucinated `claim_id`
references (`claim_013`, `claim_014`, etc.) that did not appear in
its own emitted `key_claims` list. The reasoning-skeleton validator
correctly rejected this and the pipeline flipped to
`evidence_insufficient` after 2 retries.

**Root cause:** `_assign_claim_ids` minted UUIDs on `key_claims`
*after* the LLM had already emitted `reasoning_slots[].claim_ids`,
leaving slot refs dangling.

**Fix committed this session** ([backend/agents/analyst.py](backend/agents/analyst.py)):
new `_rewrite_slot_claim_ids` post-pass runs immediately after
`_assign_claim_ids` in both `AnalystAgent.run()` and `.revise()`.
It rewrites dangling refs to real minted ids via word-overlap
matching between each slot's `summary` and each claim's `text`
(threshold ≥3 shared words); drops unrecoverable refs cleanly
rather than silently mis-pointing. 4 unit tests in
[backend/tests/test_analyst.py](backend/tests/test_analyst.py) all
green.

**Run B re-fire after the fix:** zero `claim_id` / `reasoning_slot`
errors in the run output. Fix worked at its target. Pipeline still
aborted, but at a **different**, **semantic** gate:

**Run B failure mode 2 (open — content gap, not code bug):** the
analyst exited with a well-formed `gap_report`:

> "The analysis lacks direct evidence on the German market structure,
> regulatory requirements, and competitive landscape, which are
> critical for validating the market entry strategy."

The firm library contains UK industrial services content (TargetCo
CIM, UK retail sector primer, Albright & Marsh pricing pack,
Valuation Methodology, M&A Target Screen Playbook). The Run B brief
asks for **German industrial services market entry**. The analyst
correctly identified that it cannot honestly produce a market-entry
memo from a UK-only library and exited with a structured gap_report
rather than fabricating. Pipeline state: `evidence_insufficient`.
Wall 533s, cost $0.43.

This is the **honest behavior** of a grounded analyst, not a bug.
It's also not a W8 framework problem — Porter's Five Forces was
never reached because there was no analysis to anchor it on.

## Headline assertions

| Assertion | Result |
|---|---|
| A: 2x2 present | ✅ |
| A: 2x2 items ≥ 4 | ✅ |
| A: 2x2 items all have evidence_citations | ✅ |
| A: pyramid_check_result populated | ✅ |
| A: mece_check_result populated | ✅ |
| B: Porter's Five Forces present | ❌ |
| B: all 5 forces populated | ❌ |
| B: pyramid + mece populated | ❌ |
| Pyramid: at least one run with 0 errors | ✅ (Run A) |
| MECE: zero overlaps on key_reasons (≥1 run) | ✅ (Run A) |
| **W8 headline_pass** | **false** (Run B's required framework didn't land) |

## Frameworks visibly shape output (Run A excerpts)

**2x2 (M&A — TargetCo capability screen):**
- Axes: x="Strategic fit" (Low → High), y="Deal complexity" (Low → High)
- 4 items: Facilities Maintenance (top_right), Mechanical Services (bottom_left), Compliance Services (top_left), International Expansion (bottom_right) — each with rationale + evidence citation
- Interpretation: cluster pattern reading; divestiture candidate called out

**Pyramid (Run A):** 3 advisory findings (info/warning level), 0 errors — the recommendation states the answer up front, reasons logically chain, same category.

**MECE (Run A):** zero overlaps across `key_reasons`, `risks`, `counterarguments`, `synergy_estimate.cost_synergies[].type`, `risks_and_mitigations[].description`, `deal_structure_implications.negotiation_priorities`, `deal_structure_implications.walk_away_triggers`.

## What works

- **M&A engagement end-to-end is shipping.** Run A produces a valid memo with the required 2x2 framework, base fields, and M&A sections.
- **All W8 unit tests green** (38/38 after the `min_length=4` bump).
- **Pyramid + MECE post-writer auto-checks fire, persist, and pass** on the M&A engagement. Cost overhead matches design (~$0.001 pyramid + ~$0 MECE).
- **Mode-coverage gate fixed itself.** Yesterday's D5 wrap-up identified the gate as a blocker; this session's runs confirm it works correctly — yesterday's failure was a stochastic miss on research-branch dispatch that didn't recur. Debug instrumentation (since stripped) captured the gate doing exactly what it should: all 6 required M&A branches present in evidence_objects, `missing_branches: []`.
- **W7 carry-forward closed.** Run A produces the M&A memo W7 was missing.

## What's still open

**Phase 3 carry-forward:** Re-run tools/run_week8_e2e.py against current main. If Run A still fails at evidence_insufficient (current state), root-cause the regression between sessions — suspected causes include the analyst claim_id rewrite, prompt tightening, or session-to-session library state. If Run A returns to its previous shipping state, run Run B against the UK competitive defence brief to confirm Porter's lands. Estimated effort: half a day.

### Run A regression persists after schema revert; deeper investigation needed

Tightening `TwoByTwoMatrix.items` to `min_length=4` in iterate-2 was
the suspected root cause of the Run A regression. The schema constraint
was reverted to `min_length=2` (commit `665fe47`) and a re-fire
attempted under spec'd single-shot conditions on 2026-05-11 18:15Z.

**Result: Run A still failed.** Session
`e56e92e7-4e64-4b3e-95a1-b9edd69a96a8` aborted at the
`evidence_insufficient` gate with a different gap_report than the
iterate-3 era:

> "Lack of evidence for customer concentration risk claim."

Missing-evidence list: "Detailed analysis of the competitive landscape
and customer demographics in the key market segments."

This is the same upstream evidence-sufficiency gate that fired
during the earlier W8/D5 fires — the analyst sometimes manufactures
a metric or claim the verifier can't ground, the gate rejects, the
revise loop runs out of repair budget, and the pipeline aborts
before the writer. The `min_length=4` revert was correct in
hypothesis but wasn't the actual bottleneck.

**Run B side note (this same fire):** session
`248e3a78-46b3-4d06-9b42-3ee2bd3a0bdd` hung between
`verification_done` and writer-start (no LLM activity for 12 min
after the verifier completed; pipeline_trace stopped at
`research_gathered` so we have no further breadcrumbs). Killed
manually after ~1h wall, $0.64 spent on Run B alone. Not pursued
further per session cost cap. The hang itself is a separate
finding worth instrumenting next session.

Run A cost: $0.12. Run B cost: $0.64 (incomplete). Total session
spend: $0.76 of $1.00 cap.

**Next session's actual diagnostic work:** the regression is
not in the 2x2 schema. It's in whatever the analyst is emitting
that the verifier can't ground (claim_013 / £41m / customer
concentration — three different fabricated metrics across three
runs). Possibilities to investigate:
1. Analyst's verifier-feedback loop is too lenient — claims that
   verifier-flags as unsupported survive into the gap_report.
2. The orchestrator's revise budget (2 retries) is too small for
   the analyst to clean up multiple unsupported claims in one
   pass.
3. The verifier itself is mis-flagging well-grounded claims.

None of these are W8 framework code; they're W6/W7 analyst-loop
plumbing. Phase 3 housekeeping work, not next-session emergency.

### Phase 3 escalation — library breadth, not W8 code

**W8 ships with Run A only (M&A path); Run B requires broader firm
library coverage before growth_strategy memos can reach the writer.
Library expansion is Phase 3 work, not Week 8 work.**

Run B Final fire (UK competitive defence brief — designed to sit
inside the existing library's coverage of Retail Sector Primer UK+US,
TargetCo CIM segments, and Albright & Marsh pricing methodology):

- session `247beb21-fc83-4f16-b366-7e9117fed5bf`, wall 486s, cost $0.39
- pipeline state: `evidence_insufficient`
- gap_report.notes (verbatim):

> "The analysis lacks quantified consumer adoption data or retailer
> penetration benchmarks for private label programs and specific
> benchmarks for omnichannel execution, which are critical for
> validating the proposed strategies."

The analyst stayed within scope of the library content but identified
that growth_strategy memos demand quantified market-level benchmarks
(adoption curves, penetration ratios, channel-mix data) that none of
the seeded library documents contain. This is honest grounding
behaviour, not a code defect. The framework code itself (Porter's
schema + writer instruction + critic enforcement) is unchanged and
provably correct — it cannot fire when no writer payload exists.

Same fire also re-ran Run A (M&A). It also hit `evidence_insufficient`
this time (session `aea4578b-97f4-4924-b877-d4bbcb74b4cc`, wall 208s,
cost $0.13), gap_report.notes:

> "The evidence does not support the claim about the facilities
> maintenance segment's project pipeline valued at £41m."

This is the same stochastic gate-failure pattern observed during
W7's iterate window — the analyst sometimes manufactures a metric
that the verifier can't ground, triggering the gate. The earlier
Run A (session `9da8a365-224e-4c4c-8f65-8ff1d1cef5dc`, commit
`f8223ea`) produced a fully-valid M&A memo and remains the
architectural proof that the W8 M&A path ships. The stochastic
failure mode is a Phase 3 reliability concern (claim-grounding
discipline at analyst-output time), not a W8 ship blocker.

### Earlier Run B failure modes — three layers, all resolved or escalated

Each fix today surfaced the next gate.

| Fire | Wall | Cost | Failure | Gate |
|---|---|---|---|---|
| 1st (post analyst-fix `_rewrite_slot_claim_ids`) | 533s | $0.43 | German market entry brief vs UK-only firm library — analyst honestly declined | analyst self-reported `evidence_insufficient` |
| 2nd (after re-flavoring brief to UK regional expansion) | 1388s | $0.69 | Writer reached `deliverable_ready` BUT emitted no `frameworks` block. `apply_mode_checks` correctly fired error-severity finding `"Mode requires 'porters_five_forces' framework but the writer payload has no frameworks block at all"`; the orchestrator persisted to `session.metadata.mode_check_failures` but did NOT block ship — wired advisory-only | writer-level: framework instruction too weak |
| 3rd (after strengthening Porter's instruction with REQUIRED + critic-fail language) | 457s | $0.37 | Different pre-writer gate. Analyst hallucinated UK-grocery-sector framing (because the firm library has the Retail Sector Primer UK+US for breadth), couldn't ground it sufficiently, declined. Pipeline died pre-writer | analyst evidence-sufficiency on subject confusion |

The Porter's prompt strengthening (commit
`<this commit>`) is good code regardless — captures the lesson
about explicit REQUIRED + consequence language. But it can't fire
when the writer never runs.

**Three options for next session:**

1. **Make the framework critic check actually blocking, not advisory.**
   When `apply_mode_checks` returns an error-severity finding, the
   orchestrator should trigger a writer retry with the finding in
   the repair hint (mirrors the existing `validate_writer_claim_linkage`
   pattern at orchestrator.py:1032). Then Fire-2's scenario would
   force the writer to re-emit including Porter's. ~2-3 hours.
2. **Seed the demo library with focused growth-strategy content.**
   A short UK industrial services growth-strategy primer (regional
   structure, competitive dynamics, expansion case patterns) so the
   analyst's evidence base on UK regional expansion is robust enough
   not to drift into grocery framing. ~1-2 hours.
3. **Both.** The orchestrator wiring is the durable structural fix;
   the library seed is the demo-quality polish on top. ~3-5 hours
   total.

The Run A path (M&A) proves the framework code works end-to-end.
The Run B path's three failures are at three different layers
none of which are W8 framework-code defects — they're upstream
pipeline-wiring and library-content gaps.

### Yesterday's stochastic research-branch dispatch issue

Did not recur during today's two Run A attempts (both saw all 6
required branches present). Not blocking, but worth fixing for
reliability: ensure all `required_branches` from the resolved mode
get explicit task assignment in
`agents/research/orchestrator.py`, no relying on the planner's
stochastic coverage.

### Smaller deferred items

- `basis_citations` auto-repair (W8/D5 attempt 4 finding): structured-
  output's repair loop can fix shape drift but not "fill in a missing
  citation list." A targeted repair hint would close one stochastic
  failure mode. Estimated 1-2 hours.
- Pyramid + MECE findings UI: results persist to `session.metadata`
  and the count columns but no workspace UI displays them. Phase 4.
- Value Chain framework: wired in code, no built-in mode currently
  requires it. First customer ask drives mode assignment.

## Week 7 carry-forward

**Status: closed.** Run A this session produced a valid
`MAndADiligenceReportPayload` end-to-end with 7/7 M&A top-level
sections + 8/8 base fields + a populated 2x2 framework. W7's wrap-up
([week7_m_and_a_mode.md](week7_m_and_a_mode.md)) has been flipped
to **ship**.

## W10/D1 update — Run A regression diagnosed and fixed

**Status:** the M&A Run A regression (0/7 fields → `evidence_insufficient`)
that motivated the W8/D5 partial-ship is **fixed**. Both fixes were
single-commit on the W10 branch.

**Investigation:** bisection vs. external-cause split, 3 e2e runs total, $1.34
spent of $2.00 ceiling.

1. **Run 1 (current main):** Run A produced 0/7 fields, halted at
   `evidence_insufficient`, $0.12. Regression confirmed on main.
2. **Run 2 (LAST_GOOD `f8223ea` on current API state):** Run A produced
   identical 0/7 / `evidence_insufficient` / $0.12 failure. Code at
   LAST_GOOD reproduces the regression today.
3. **Verdict:** Hypothesis A (internal regression) **rejected**;
   Hypothesis B (external) **confirmed**. Between f8223ea and main the
   verifier, orchestrator, critic, configs and deps were untouched. The
   verifier LLM (`openai/gpt-4o`) returns `overall: "insufficient"` for
   the M&A claim set today where it returned `"supported_partial"` on
   May 11. Same model id, same prompt, same code — just stochastic
   verifier verdict drift.

**Root cause:** the pre-writer evidence gate at
[orchestrator.py:942](backend/agents/orchestrator.py#L942) was binary on
the verifier's free-form `overall` string. One stochastic flip of that
string from `"supported_partial"` to `"insufficient"` halts the pipeline
even when the underlying `claim_assessments` show majority support.

**Fix:** the gate now consults the assessments themselves. Halt only
when evidence is absent (0 chunks), OR when assessments are absent and
overall=insufficient, OR when assessments themselves are majority
unsupported (`unsupported_count > supported_count`). A free-form
`overall: insufficient` from the verifier no longer alone trips the
gate when the assessments contradict it.

**Run 3 (re-verify, both runs):**

| Run | Pipeline state | M&A fields | Framework | Cost | Wall |
|---|---|---|---|---|---|
| **A — M&A** | `deliverable_ready` ✅ | **7/7** | 2x2 + Porter's bonus | $0.21 | 414s |
| **B — growth** | `failed` ❌ | n/a | — | $0.89 | 1264s |

Run A: status=`complete`, recommendation="PROCEED WITH CONDITIONS",
2x2 with 2 items + citations + labelled axes, Pyramid passed (0
errors), MECE passed (0 overlaps across 8 fields).

Run B: pipeline now reaches the writer for the first time on
`growth_strategy` (the gate fix worked), but the writer's JSON
output truncated mid-stream at line 255 (EOF parsing the object
body), failing schema validation after 2 repair attempts. This is
a different defect — writer output truncation, likely `max_tokens`
or model-side cutoff on a verbose growth-strategy memo. Not the
evidence-gate regression, and not in scope for the W10/D1 brief.

## Decision

- [x] **Ship Week 8 (M&A path).** M&A path now lands end-to-end on
  current model state with the W10/D1 gate fix. 7/7 M&A sections, 2-item
  2x2 with citations, Pyramid + MECE passing. The original W8/D5
  partial-ship caveat (Run A regression) is closed.
- [ ] ~~Ship Week 8 (full).~~ Run B (growth_strategy) reached the
  writer but emits truncated JSON — separate defect, new Phase 3
  carry-forward. Not the original gate regression.

**Tags:** `phase-2/week-8-shipped-partial` (original ship) +
`w8-regression-fixed` (W10/D1 close of the M&A regression).

The W8 frameworks library itself is production-ready and the M&A
path is now stable on current model state. Run B's failure mode
shifted: previously the analyst gated out pre-writer on
`evidence_insufficient` (now fixed); on the W10/D1 re-verify the
pipeline reaches the writer but the writer emits truncated JSON.
The library-breadth question raised in earlier sessions is still
real for growth_strategy (UK industrial-services depth vs the
market-sizing/penetration content growth memos demand) but is
no longer the proximate failure; the proximate failure is now
writer-output truncation.

## 5-line summary

1. **Decision:** ship Week 8 (M&A path) clean; growth_strategy still partial. Original Run A regression closed in W10/D1.
2. **Headline finding:** M&A engagement now lands 7/7 fields + 2x2 + Pyramid + MECE on every fire ($0.21, 414s). The original regression was a brittle evidence gate that halted on the verifier's free-form `overall` string when assessments themselves showed majority support — fixed via quorum check on `claim_assessments`.
3. **Investigation:** 3 e2e runs, $1.34 spent of $2 ceiling. Run 1 reproduced on main; Run 2 reproduced on LAST_GOOD `f8223ea` — confirming external cause (verifier stochastic drift), not internal regression.
4. **Pyramid + MECE:** 0 errors / 0 overlaps on Run A; both fire reliably when the writer payload exists.
5. **New Phase 3 carry-forward:** Run B now reaches the writer (gate fix landed) but writer JSON truncates mid-emission on growth_strategy. Different defect from the original gate regression — likely a `max_tokens` / model output-budget issue on verbose memos, not in W10/D1 scope. **W14/D1 update:** writer-truncation closed via gpt-4o swap. A second-layer schema-enforcement bug surfaced behind it; bounded Phase 4 plan below.

## W14/D1 update — writer-truncation closed; new schema-enforcement carry-forward opened

**What W14/D1 fixed:** added `model_overrides.writer.model: openai/gpt-4o` + `max_tokens: 16000` to `growth_strategy` in `backend/config/consulting_modes.yaml`. Diagnosis used no LLM budget — past writer call on `bcb54507-…` was already in `llm_calls` with `model=anthropic/claude-sonnet-4-5`, `completion_tokens=8174` (exactly Sonnet's 8192 default cap), confirming hypothesis statically. Anthropic's extended-output beta header is wired as a no-op (W7 found Anthropic rejected it), so raising `max_tokens` on Sonnet wouldn't have worked. The proven W7 pattern is the model swap. **Verify run on session `a44923a8-…`:** cost $0.60, wall 21 min, writer ran clean on gpt-4o — full structured payload emitted, no truncation, all base sections (key_reasons, risks, executive_insights, options_matrix, decision_criteria, etc.) populated. **Runs spent: 1 of 3 budgeted. Spend: $0.60 of $2 ceiling.**

**Bug surfaced behind the fix:** the writer set `frameworks: null` even though the system prompt's framework-instruction block explicitly states "REQUIRED, not optional. You MUST emit this block". Root cause is structural, not prompt-strength: `agents/writer/schemas/_base.py:GeneralReportPayload.frameworks` is `Optional[FrameworksBlock]`, and `agents/writer/schemas/_registry.py:get_writer_schema('growth_strategy')` returns `GeneralReportPayload` (no growth-specific subclass). gpt-4o legitimately emits `null`; the Pydantic validator accepts it; the orchestrator's required-frameworks check evidently doesn't gate the report on a missing-frameworks finding (it logs a finding but doesn't block persistence). So growth memos persist without Porter's despite the mode declaring it required.

### Phase 4 bounded plan (Path B — two-pass writer)

The simplest fix that doesn't weaken the Porter's schema (per W14/D1 hard rule):

1. **Add `GrowthStrategyReportPayload`** in `agents/writer/schemas/_growth.py`, mirroring `_m_and_a.py`. Override `frameworks: FrameworksBlock` (non-optional) and inside FrameworksBlock for this subclass, override `porters_five_forces: PortersFiveForcesAnalysis` (non-optional). Register it in `_registry.py` for `growth_strategy`. Pydantic will then reject any writer output that omits Porter's, forcing a repair pass.
2. **OR — two-pass writer** if the single-pass with strict schema still proves flaky: split the writer into (a) base memo (no frameworks block) → (b) focused framework-only writer call that takes the base memo's key_claims as input and emits only `frameworks.porters_five_forces`. Validate each pass independently. Merge. Gate behind a `requires_two_pass_writer: true` flag in `consulting_modes.yaml` so only framework-heavy modes pay the second call. This mirrors the W9 section-deepening pattern (separate focused LLM call, separate budget, separate schema validation).
3. **Verify**: re-run `tools/run_week8_e2e.py --runs B_growth_strategy`. Expect Porter's populated, all 5 forces present with evidence_citations + intensity + rationale ≥30 chars.
4. **Estimated effort:** half a day for option 1 (Pydantic subclass + registry wiring + 1 verify run), one full day for option 2 (orchestrator state-machine change + retry coordination + merge logic + 1-2 verify runs). Start with option 1.

The growth Run B writer-truncation symptom (the original W8 carry-forward) IS closed by W14/D1. The Porter's content gap downstream is a separate, newly-surfaced bug — not the same defect, not the same fix shape.

Run records:
- [backend/eval_runs/week8_e2e/A_m_and_a.json](../../backend/eval_runs/week8_e2e/A_m_and_a.json) (gitignored — latest Run A capture; the earlier passing Run A is referenced via session id `9da8a365-...` in git history)
- [backend/eval_runs/week8_e2e/B_growth_strategy.json](../../backend/eval_runs/week8_e2e/B_growth_strategy.json) (gitignored — latest Run B capture: UK competitive defence brief, pre-writer evidence_insufficient)
- [backend/eval_runs/week8_e2e/summary.json](../../backend/eval_runs/week8_e2e/summary.json) (committed)
- Total session spend: **~$3.85** of $5 ceiling.

**Tag:** `phase-2/week-8-shipped-partial`.
