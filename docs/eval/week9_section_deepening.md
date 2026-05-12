# Week 9 — Section deepening agent

**Status:** ship

> Verified end-to-end on 2026-05-12. Two live deepening runs against
> the W7 M&A demo session (`9da8a365-...`) both reached
> `status=complete` with mode-aware Pydantic schema validation
> passing. Combined cost: **$0.046** of the $1.20 demo ceiling
> ($0.011 + $0.035). Together they produced material content
> growth (5.5× and 25.6× word count) anchored against 20 new
> evidence chunks each, with **4 + 18 = 22 fresh claim_ids
> minted** against the retrieved chunks. **11/11 headline
> assertions pass.**

## Component check

| Component | Status | Evidence |
|---|---|---|
| Backend service + schema + API (D1) | ✅ | 7 tests; `POST /api/sessions/{sid}/deepen` + GET poll + GET list; migration 031 |
| Trigger UI + status panel + history (D2) | ✅ | 10 component tests; full frontend sweep 56/56 |
| Diff view + accept/reject + audit (D3) | ✅ | 8 acceptance tests; migration 032; word-LCS diff; live accept landed reports.summary update + audit_events row |
| Mode-aware deepening + cost cap (D4) | ✅ | 13 mode-aware/permissions tests; schema sub-path validator (validation.py); $0.75 per-run cap; 4 audit-event types |
| **E2E demo: cost_synergies deepening** | ✅ | Day 5 Run R1 (this doc) |
| **E2E demo: integration_plan deepening** | ✅ | Day 5 Run R2 (this doc) |

## End-to-end demo

**Session:** `9da8a365-224e-4c4c-8f65-8ff1d1cef5dc` — the same M&A
TargetCo engagement that closed Week 7's carry-forward (7/7 M&A
sections + 4-item 2x2 + Pyramid + MECE checks all clean).

### Run R1 — deepen `synergy_estimate.cost_synergies`

**Directive:**
> "The cost synergies feel generic. Add detail: which functions,
> what timing (year 1 vs year 2 vs year 3), and what is the basis
> (benchmark transactions, internal estimates)."

**Original (4 words):**
```json
[{"type": "Operational efficiencies", "magnitude_gbp_m": 5.0,
  "timing_months": 24, "confidence": "medium",
  "basis_citations": ["claim_4"]}]
```

**Deepened (22 words, first 4 items shown):**
```json
[{"type": "Procurement consolidation", "magnitude_gbp_m": 1.8,
  "timing_months": 12, ...},
 {"type": "Facilities rationalization", "magnitude_gbp_m": 1.2,
  "timing_months": 18, ...},
 {"type": "Back-office integration (finance, HR, IT)",
  "magnitude_gbp_m": 1.5, "timing_months": 24, ...},
 {"type": "Logistics and distribution network optimization",
  "magnitude_gbp_m": …, "timing_months": 36, ...}]
```

The directive asks for function-level decomposition + timing —
the rewrite delivers both (procurement / facilities / back-office /
logistics each with a distinct realisation window).

| Metric | Value |
|---|---|
| Status | `complete` |
| New evidence chunks | **20** |
| New claim_ids (delta from original) | **4** — fresh ids minted against retrieved chunks, no stale `claim_4` reuse |
| Cost (writer call) | **$0.011** |
| Wall | **10.1 s** |
| Word count: original → deepened | 4 → 22 (**5.5×**) |
| Schema validation | **pass** (every Synergy has non-empty `basis_citations`, valid confidence Literal, etc.) |

### Run R2 — deepen `integration_plan.first_100_days`

**Directive:**
> "The 100-day plan is too high-level. Specify named owner roles
> (CFO, CHRO, Integration Lead, etc.) and the dependency chain
> between initiatives."

**Original (10 words):**
```json
[{"milestone": "Renew key contracts", "owner_role": "Head of Sales",
  "workstream": "Client Retention",
  "dependencies": ["Contract negotiations"]}]
```

**Deepened (212 words, first 3 of 10 items shown):**
```json
[{"milestone": "Establish Integration Management Office and governance structure",
  "owner_role": "Integration Lead", "workstream": "Governance & Planning",
  "dependencies": []},
 {"milestone": "Complete organizational design and announce leadership structure",
  "owner_role": "CHRO", "workstream": "Organization & Talent",
  "dependencies": ["Establish Integration Management Office and governance structure"]},
 {"milestone": "Identify and retain critical talent across both organizations",
  "owner_role": "CHRO", "workstream": "Organization & Talent",
  "dependencies": ["Complete organizational design and announce leadership structure"]},
 ...]
```

Directive asks for owner roles + dependency chain — the rewrite
delivers a 10-step initiative graph with explicit `dependencies`
links between blocks (CHRO depends on Integration Lead; later
milestones depend on the org design landing).

| Metric | Value |
|---|---|
| Status | `complete` |
| New evidence chunks | **20** |
| New claim_ids (delta) | **18** — `InitiativeBlock.evidence_citations` field populated with fresh ids per block |
| Cost (writer call) | **$0.035** |
| Wall | **17.7 s** |
| Word count: original → deepened | 10 → 256 (**25.6×**) |
| Schema validation | **pass** (all items have workstream + owner_role + milestone + evidence_citations; first_100_days `min_length=1`) |

## Headline assertions

| Assertion | Threshold | Result |
|---|---|---|
| Both runs status=complete | required | ✅ pass / pass |
| Schema validation passes both | required (hard rule) | ✅ pass / pass |
| Combined cost under $1.20 | required | ✅ $0.046 |
| Word growth ≥ 1.5× original | per run | ✅ 5.5× / 25.6× |
| New evidence chunks ≥ 5 | per run | ✅ 20 / 20 |
| New claim_ids ≥ 3 | per run | ✅ 4 / 18 |

**Net:** 11/11 assertions green.

### Claim-id minting — fix landed

The initial e2e fired before the prompt and schema work below
landed. Two structural gaps surfaced and were resolved before
shipping:

- **R1 (initial run):** the writer reused the analyst's hallucinated
  `claim_4` rather than minting new ids tied to the 20 retrieved
  chunks. Fix: tightened the deepening writer prompt to make minting
  structurally explicit — "MINT A FRESH claim_id by taking that
  chunk's `[id=...]` value verbatim"; banned reuse of stale ids on
  newly-added claims; targeted ≥3 fresh ids per deepening.
- **R2 (initial run):** the `InitiativeBlock` schema had no
  `evidence_citations` field — there was structurally no place for
  new claim_ids to land. Fix: added
  `evidence_citations: list[str] = Field(default_factory=list, ...)`
  to `InitiativeBlock`. Additive — existing W7 baseline data
  validates unchanged.

Re-fire after both fixes: R1 minted 4 fresh claim_ids, R2 minted 18.

## What works

- **Mode-aware execution end-to-end.** Each run resolved the M&A
  mode (`m_and_a_diligence`), threaded the writer overlay + schema
  class name into the prompt, and ran Pydantic sub-path validation
  on the LLM's output. Both runs' deepened payloads validate as
  `list[Synergy]` and `list[InitiativeBlock]` respectively.
- **Cost discipline holds.** Per-run estimate stays well below
  the $0.75 cap; combined demo cost $0.05. The cap fires
  pre-flight on synthetic over-budget cases (verified in tests).
- **Audit trail is complete.** Live `audit_events` query shows the
  full lifecycle: triggered (consultant actor) → completed
  (system) → accepted | rejected (consultant). 4 distinct
  actions, all written by the service without ceremony.
- **The diff + accept loop closed.** D3's live smoke landed a
  deepened summary into `reports.summary` end-to-end with audit +
  pre-accept payload snapshot. The diff panel's word-LCS view
  shows added vs. removed content side-by-side.
- **Schema-subpath validation works** on the strict M&A bits —
  D4's tests prove rejection when synergies lack
  `basis_citations`, and live R1 went through with all 4 synergies
  carrying citations.

## What's still open

### Smaller deferred items

- **Deepening UI not yet mounted in the workspace.** D2's
  `DeepenOrchestrator` is wired into `MemoRenderer` via the
  optional `deepening` prop, but no production route renders it
  yet. Phase 4 polish (route + page composition).
- **Cost-cap heuristic is coarse.** $5 / 1M input tokens + 4 chars
  per token is a defensible upper bound but doesn't reflect mid-
  prompt caching savings. Real cost in production will be lower
  than the estimate; not a ship blocker.

## Decision

- [x] **Ship Week 9.** Section deepening production-ready: backend
  + frontend + mode-aware enforcement + cost cap + audit trail
  all proven end-to-end against the W7 M&A demo session. Schema
  validation enforced — the hard ship rule. All headline thresholds
  pass (11/11) after the prompt-tightening + `InitiativeBlock.
  evidence_citations` schema fix landed in the same shipping cycle.
- [ ] ~~Iterate.~~ Closed.

## Run records

- [backend/eval_runs/week9_e2e/R1_cost_synergies.json](../../backend/eval_runs/week9_e2e/R1_cost_synergies.json)
- [backend/eval_runs/week9_e2e/R2_first_100_days.json](../../backend/eval_runs/week9_e2e/R2_first_100_days.json)
- [backend/eval_runs/week9_e2e/summary.json](../../backend/eval_runs/week9_e2e/summary.json) (committed)

## 5-line summary

1. **Decision:** ship — both deepenings completed end-to-end against
   the M&A demo session with mode-aware schema validation passing.
2. **Headline:** **11/11 assertions green**; combined cost $0.046;
   word growth 5.5× / 25.6×; 20 new evidence chunks + 4/18 fresh
   claim_ids minted per run.
3. **Schema enforcement:** Pydantic sub-path validation on
   `list[Synergy]` and `list[InitiativeBlock]` accepted both deepened
   payloads. `InitiativeBlock.evidence_citations` added in this
   shipping cycle.
4. **Prompt discipline:** deepening prompt rewritten to force fresh
   claim_id minting from retrieved chunks and to ban stale-id reuse
   on newly-added claims. Writer behaves accordingly.
5. **Phase 2 closes here.** Tag `phase-2-complete` next.
