# Week 8 — Frameworks library

**Status:** iterate (M&A path ships; growth_strategy path blocked on a pre-existing W6/D2 analyst bug surfaced during W8/D5)

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
| **E2E demo: M&A produces a 2x2** | ✅ | **Run A** (W8/D5 iterate): 4 items, all with citations, axes labeled, valid memo |
| **E2E demo: growth produces Porter's** | ❌ | **Run B**: pipeline aborted at reasoning-skeleton gate, never reached writer; Porter's not produced |
| **Pyramid + MECE fire and persist** | ✅ (partial) | Fire and pass cleanly on Run A; couldn't fire on Run B because the writer never ran |

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

**Why Run B aborted (deterministic, two attempts confirmed):**
The analyst on `growth_strategy` mode populates the mode's reasoning_slots
(market_attractiveness, capabilities, competition, risks) with
hallucinated `claim_id` references (`claim_013`, `claim_014`,
`claim_016`, `claim_017`) that do not appear in its own emitted
`key_claims` list. The reasoning-skeleton validator (W6/D2) correctly
rejects this and triggers the analyst revise loop; the analyst
hallucinates the same shape on retry. After 2 retries the pipeline
flips to `evidence_insufficient` with gap_report "Report mode
'growth_strategy' requires all configured reasoning slots with summaries
and claim links."

This is a **W6/D2 analyst-side claim-id integrity bug**, not a W8
regression. The W8 framework code never gets reached. It's specific
to `growth_strategy` (Run A's M&A engagement does NOT exhibit this).
Likely root cause: the analyst's claim-id assignment runs after
reasoning_slot population, so slot references can point at not-yet-
minted claim ids; M&A's reasoning_slots may happen to use a smaller
slot set that hasn't surfaced this latent bug.

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

### Run B — growth_strategy analyst claim-id hallucination

The reasoning-skeleton gate (W6/D2) correctly rejects the analyst's
output on `growth_strategy` mode because the analyst references
`claim_id` values in its `reasoning_slots` that don't exist in its own
`key_claims` list. Two attempts in this session both failed the same
way; it's deterministic, not stochastic. The fix is W6/D2 territory,
not W8:

1. Most likely: enforce that `_assign_claim_ids` runs **before** the
   analyst's slot-population pass writes `claim_ids` into
   `reasoning_slots[].claim_ids` — OR add a post-pass that rewrites
   slot claim_ids to actual minted ids by matching them to claim text.
2. Alternative: post-validate at the analyst layer (not just at the
   skeleton gate downstream) so the analyst's own retry sees the
   error in time to fix it on its own.

Estimated: 1-3 hours. Should land in Week 9 housekeeping before any
new feature work depends on growth_strategy producing a valid memo.

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

## Decision

- [ ] **Ship Week 8 as fully verified.** Cannot do: Run B's required
  framework (Porter's) didn't land, the writer never ran on Run B.
  Per spec hard rule "Don't ship Week 8 if either required framework
  is missing on its run."
- [x] **Iterate (continued).** Two iterate signals from W8/D5:
  - **(a) M&A path is genuinely shipping.** No further W8 work needed
    on M&A — the architecture is structurally complete, tests pass,
    e2e produces the memo, pyramid + mece auto-check.
  - **(b) growth_strategy path is blocked one layer upstream of W8.**
    The W6/D2 analyst-side claim-id hallucination needs a targeted
    fix (1-3 hours) before Run B will ever reach the writer.

The W8 frameworks library itself is production-ready; one analyst
bug stands between us and a fully-verified ship. Week 9 housekeeping
should land that fix first.

## 5-line summary

1. **Decision:** iterate — M&A path ships, growth_strategy path blocked on a pre-existing W6/D2 analyst bug surfaced during W8/D5.
2. **Headline finding:** Run A produced a valid M&A memo with 4-item 2x2, 7/7 sections, 8/8 base fields, pyramid + mece passed — closes the W7 carry-forward.
3. **Pyramid + MECE pass rates:** Pyramid 0 errors / 3 advisory findings (1 run); MECE 0 overlaps across 7 fields (1 run); both gated on a writer payload existing.
4. **Week 7 carry-forward:** **closed.** W7 wrap-up flipped to ship.
5. **Open for Week 9:** fix the analyst's reasoning_slot → key_claims claim-id integrity (W6/D2 housekeeping); then a single Run B verifies Porter's. After that, W8 flips to ship.

Run records:
- [backend/eval_runs/week8_e2e/A_m_and_a.json](../../backend/eval_runs/week8_e2e/A_m_and_a.json) (gitignored — Run A captured payload)
- [backend/eval_runs/week8_e2e/B_growth_strategy.json](../../backend/eval_runs/week8_e2e/B_growth_strategy.json) (gitignored — Run B captured trace)
- [backend/eval_runs/week8_e2e/summary.json](../../backend/eval_runs/week8_e2e/summary.json) (committed)
- Total session spend across 4 runs (A x2, B x2): **$1.44** of $5 ceiling.
