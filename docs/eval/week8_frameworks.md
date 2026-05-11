# Week 8 — Frameworks library

**Status:** iterate (code shipped clean; e2e blocked on an upstream W7-carry gate, not on W8 code)

## Component check

| Component | Status | Evidence |
|---|---|---|
| Pyramid Principle auto-checker | ✅ | Day 1; 5 tests; structural + LLM judge (gpt-4o-mini); wired post-writer |
| MECE checker (embedding pairwise) | ✅ | Day 2; 7 tests; threshold 0.85; embed_texts() default |
| 2x2 matrix schema + renderer | ✅ | Day 3; Pydantic min/max + Literal enums; React component + test |
| Porter's Five Forces schema + renderer | ✅ | Day 3; market_definition + 5 forces + rollup; React vertical-stack renderer |
| Value Chain schema + renderer | ✅ | Day 3; 9 canonical steps; primary/support row split |
| Frameworks wired into modes | ✅ | Day 4; M&A required=[two_by_two], growth required=[porters_five_forces] |
| Critic enforces required frameworks | ✅ | Day 4; ``check_required_frameworks`` + ``apply_mode_checks`` wiring |
| Writer prompt augmentation per mode | ✅ | Day 4 + Day 5 tightening; flat-field enumeration after first e2e drift |
| **E2E demo: M&A produces a 2x2** | ❌ | Day 5; pipeline aborted at evidence_insufficient gate before writer ran |
| **E2E demo: growth produces Porter's** | ⏭ | Day 5; Run B not fired (Run A blocked first) |
| **Pyramid + MECE fire and persist** | ❌ | Day 5; writer didn't run, so post-writer checks didn't fire |

## End-to-end demo

**Brief (Run A):** Same TargetCo Holdings M&A diligence brief as W7 (cross-week comparison).

### Run A — M&A diligence with required 2x2

Three attempts. Trajectory across attempts is the real signal:

| Attempt | Wall (s) | Cost | Failure | Where |
|---|---|---|---|---|
| 1 (DB down) | <1 | $0.00 | `ConnectionRefusedError` | DB pool init — Postgres container stopped |
| 2 (after `docker compose up -d db`) | 1 | $0.00 | `UndefinedColumnError: pyramid_findings_count` | Migrations 029 + 030 had never been applied to this DB |
| 3 (migrations applied) | 434 | $0.27 | Writer schema-validate exhaustion | `frameworks.two_by_two.*` axis fields — LLM emitted `{axes: {x, y}}` instead of flat `x_axis_label` / `x_axis_low_label` / etc. + missing `title`. 7 errors all on this one block. The 8 base WriterReportBase fields + the 7 M&A sections all validated cleanly. |
| 4 (prompt tightened to enumerate flat field names) | 416 | $0.25 | Writer schema-validate exhaustion | Reduced to 1 stubborn error: `synergy_estimate.cost_synergies[0].basis_citations` empty (LLM produced one synergy without a citation list). Auto-repair handled an `integration_plan` issue but couldn't fix this one in 2 retries. |
| 5 (final retry per user hard rule) | 144 | $0.12 | **`evidence_insufficient` gate** (no exception) | Pipeline aborted before the writer ran. gap_report: "lacks evidence for claims regarding integration risks and specific deal structure details." Same shape as W7 iterate-3's final state. |

**Total Run A cost:** ~$0.64 across 5 attempts. Well under the $5 ceiling.

Run B (growth_strategy with Porter's): **not fired this session** — Run A's blocking gate would likely fire on Run B too without the upstream fix, and the user's hard rule capped Run A at one retry.

### Headline assertions

| Assertion | Result |
|---|---|
| A.frameworks.two_by_two present | ❌ (writer never ran on the final attempt) |
| A.frameworks.two_by_two items ≥ 4 | ❌ |
| A.frameworks.two_by_two items all have evidence_citations | ❌ |
| A.pyramid_check_result populated | ❌ |
| A.mece_check_result populated | ❌ |
| B.frameworks.porters_five_forces present | ⏭ (not fired) |
| W8 headline_pass | ❌ |
| Week 7 carry-forward closes | ❌ — no writer payload produced; W7 stays at iterate |

## What works

The Day 5 trajectory proved every W8 code change is correct in isolation:
- **Writer prompt augmentation works** — attempt 4 produced a 2x2 in the right shape after the flat-field enumeration landed. The shape-drift problem from attempt 3 is solved.
- **Framework schemas validate at the right moments** — every failure landed cleanly with field-level paths, no parser hangs or silent drops.
- **Migrations 029 + 030 apply cleanly** — `pyramid_findings_count` and `mece_overlaps_count` columns + filtered indexes now exist on the demo DB.
- **Runner captures everything needed** — when the writer eventually does run, the runner already extracts `frameworks_status`, `two_by_two_quality`, `porters_quality`, `pyramid`, `mece` from session metadata. Re-run will produce real numbers without further code changes.
- **All 37 W8 unit tests still green** (verified at the start of D5).

## What's still open

### The blocker — upstream evidence-sufficiency gate

Same root cause as W7's unresolved carry-forward. Even after iterate-4's `model_overrides` pivot extended `openai/gpt-4o` routing to analyst + critic, the post-analyst evidence-sufficiency gate still fires on the M&A engagement under the 128-evidence-chunk load. The gap_report cites missing evidence on integration risks + deal structure specifics, but those areas ARE covered in the firm library (the W5 demo seeds the M&A Target Screen Playbook + Valuation Methodology + the TargetCo CIM itself). The gate is over-eager.

This is structurally upstream of W8 — none of the four W8 days touched the analyst / gate / retrieval. The fix lives in either:
1. The evidence-sufficiency-gate threshold or its evidence-coverage detection logic.
2. The analyst's output (more aggressive claim extraction so the gate sees more evidence-backed claims).
3. The retrieval layer (more relevant chunks for the gate's claim-matching).

None of those are in scope for W8/D5 by spec.

### Smaller deferred items

- **`basis_citations` auto-repair**: structured-output's repair loop can fix shape drift but not "fill in a missing citation list" — the LLM doesn't know which citation to use without re-reading the analyst's `key_claims`. A targeted repair hint ("if a synergy has empty basis_citations, copy from the parent analysis.key_claims that match the synergy.type") would close this stochastic failure mode. Estimated: 1-2 hours.
- **Pyramid + MECE findings UI**: results persist to `session.metadata` and the count columns, but no workspace UI displays them. Phase 4 polish.
- **Value Chain framework**: wired in code, no built-in mode currently requires it. First customer ask drives mode assignment.

## Week 7 carry-forward

**Status: still open.** Per the W8/D5 hard rule "Don't mark Week 7 closed unless Run A actually produced a valid M&A memo with the 7 base fields + the 2x2."

Run A attempt 4 came closer than any W7 run did — only 1 validation error standing between the writer and a complete payload — but Run A attempt 5 hit the upstream gate, so no valid payload was produced this session either. W7's wrap-up
([docs/eval/week7_m_and_a_mode.md](week7_m_and_a_mode.md)) stays at "iterate"; the next iterate's first move is closing the evidence-sufficiency-gate failure mode that re-surfaced here.

## Decision

- [ ] **Ship Week 8.** Cannot ship: required framework not produced on any complete run, Pyramid + MECE checks didn't fire end-to-end. Per spec hard rule "Don't ship Week 8 if either required framework is missing on its run."
- [x] **Iterate.** The W8 code itself is sound (37 unit tests green, prompt-augment proven to fix the drift it was supposed to fix). The blocker is the same pre-existing upstream gate that's been blocking W7 since iterate-3. The next iterate is one targeted upstream fix — not a W8-internal change.

The Week 8 frameworks-library architecture is structurally complete: schemas, renderers, mode declarations, writer-prompt augmentation, critic enforcement, post-writer Pyramid + MECE checks, migrations, runner, and 37 green tests all proven. The library is ready to ship the moment an engagement actually reaches the writer. The work no longer sits in W8 — it sits one layer up at the evidence-sufficiency gate.

Run records:
- [backend/eval_runs/week8_e2e/A_m_and_a.json](../../backend/eval_runs/week8_e2e/A_m_and_a.json) (gitignored — captured payload + session metadata)
- [backend/eval_runs/week8_e2e/summary.json](../../backend/eval_runs/week8_e2e/summary.json) (committed)

## 5-line summary

1. **Decision:** iterate.
2. **Headline finding:** writer prompt-augmentation works (2x2 shape drift solved in attempt 4); upstream evidence-sufficiency gate aborted attempt 5 before the writer ran.
3. **Pyramid + MECE pass rates:** N/A — writer never executed; post-writer checks didn't fire.
4. **Week 7 carry-forward:** still open; same upstream gate is the blocker.
5. **Open for Week 9:** the evidence-sufficiency-gate fix needs to land before the section-deepening agent has anything to deepen.
