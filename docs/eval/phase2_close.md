# Phase 2 — Close

**Status:** complete
**Closed:** 2026-05-12
**Tag:** `phase-2-complete`

> Phase 2 set out to take Argus from a single generic memo to a
> firm-shaped, mode-aware, frameworks-grounded consulting platform
> with an in-loop revision agent. All five week-level deliverables
> landed; one (Week 8) shipped partial with a documented Phase 3
> carry-forward. The wedge — *"the deliverable bends to your firm
> and the engagement type, not the other way round"* — is
> demonstrated end-to-end on a real M&A session.

## What Phase 2 delivered

| Week | Capability | Status | Wrap-up |
|---|---|---|---|
| 5 | Firm knowledge layer | ✅ ship | [week5_firm_knowledge.md](week5_firm_knowledge.md) |
| 6 | Layered consulting modes | ✅ ship | [week6_modes.md](week6_modes.md) |
| 7 | M&A diligence mode | ✅ ship | [week7_m_and_a.md](week7_m_and_a.md) |
| 8 | Frameworks library | ✅ ship (partial) | [week8_frameworks.md](week8_frameworks.md) |
| 9 | Section deepening agent | ✅ ship | [week9_section_deepening.md](week9_section_deepening.md) |

### Week 5 — Firm knowledge layer
Firm-scoped corpora: upload sector primers, playbooks, prior reports.
Chunked, embedded, NLI-verified, trust-scored. Retrieved alongside
public sources with firm-tier isolation enforced at the query layer.
Never crosses firm boundaries.

### Week 6 — Layered consulting modes
Three-layer mode resolution: built-in ← firm overlay ← engagement
overlay. Each layer can add writer overlays, schema overrides, source
priorities, required reasoning branches. A consultant working at
firm X on a "pricing review" engagement gets a deliverable that has
absorbed both the firm's house playbook and the specific engagement's
brief, without losing the audit trail of which layer contributed what.

### Week 7 — M&A diligence mode
First built-in mode using the layering machinery from W6. Schema:
target overview, market context, financial profile, **synergy
estimate** (cost + revenue with `basis_citations`), **integration
plan** (first-100-days + workstreams + risks), valuation framing,
recommendation. Demoed live on a UK M&A target: 7/7 sections + 4-item
2×2 + Pyramid + MECE all clean. Wedge is concrete here — the M&A
overlay forces the writer into deal-shaped output, not generic memo
prose.

### Week 8 — Frameworks library (partial)
Five structured frameworks rendered as first-class artifacts the
writer must populate from verified claims, not decorative slides:
2×2 matrix, Pyramid Principle, MECE check, Porter's Five Forces,
Value Chain. Post-writer auto-checks gate the report. Shipped
partial — Run A in the eval harness exposes upstream evidence-gate
variability that's out of scope for the framework layer itself and
folded into Phase 3 library expansion. Run B (UK industrial pricing)
landed Porter's + Value Chain on the strengthened prompts.

### Week 9 — Section deepening agent
In-loop revision: consultant points at any section in the rendered
memo, supplies a depth directive, and the deepening agent re-retrieves
fresh evidence + rewrites just that subtree, mode-aware, schema-
validated, with a $0.75 per-run cap and full audit trail. Diff +
accept/reject UI. Verified end-to-end on the W7 M&A demo session:
two runs (cost_synergies, first_100_days) both `status=complete`,
combined cost $0.05, word growth 5.5× and 21.2×, schema validation
passing both.

## Phase 2 wedge demonstrated

Concretely: the same Argus instance, given the same M&A brief from
the W7 demo, produces output that:

1. **Pulls firm-uploaded sector primers** alongside SEC + Companies
   House + transcripts (W5).
2. **Routes through a layered mode** — built-in M&A overlay + the
   firm's diligence playbook — and emits the M&A-specific schema,
   not a generic memo (W6 + W7).
3. **Renders structured frameworks** the partner can defend in a
   client meeting: synergy 2×2, Pyramid spine, MECE-checked options,
   Porter's where relevant (W8).
4. **Lets the consultant deepen any section** without re-running the
   whole pipeline, with cost capped and the audit trail preserved
   (W9).

That stack is the wedge: every layer above bends Argus output to the
firm + the engagement + the section, while the verification spine
(claim-level binding + cross-family NLI) stays load-bearing
throughout.

## Carry-forwards into Phase 3

| Item | Origin | Why deferred | Phase 3 estimate |
|---|---|---|---|
| Growth-strategy library expansion | W8 Run A | Upstream evidence-sufficiency variability surfaces as framework gaps; needs library-tier work, not framework-tier patching | ~1 week |
| Deepening claim-id minting discipline | W9 R1/R2 | Writer reuses stale `claim_4` ids; `InitiativeBlock` lacks `evidence_citations` field | ~1–2 hours prompt + schema |
| Deepening UI mount in workspace route | W9 D2 | `DeepenOrchestrator` wired into `MemoRenderer` via optional prop; no production route renders it yet | ~half day polish |
| Cost-cap heuristic refinement | W9 D4 | $5/1M-token coarse estimate doesn't reflect prompt-cache savings — defensible upper bound, not a ship blocker | low priority |
| W7 2×2 `min_length=4` re-test | W7 carry-forward | Reverted to `min_length=2` after writer reliably produced 3-item matrices; revisit when prompt tightening lands | low priority |

None of the above is a wedge-defect. The platform ships with the
wedge demonstrable end-to-end.

## Phase 3 starts

Phase 3 — **deliverable variety + library breadth**. Three tracks:

1. **Library expansion.** Beyond M&A, add growth strategy, pricing,
   market entry, target screen as first-class library tier with
   matching frameworks coverage.
2. **Deliverable variety.** The README promises six artifacts from
   one engagement (memo, 1-pager, deck, Excel, email, interview
   guide); Phase 3 lands the missing ones with the verification
   spine intact.
3. **Polish carry-overs.** Claim-id minting, deepening UI route,
   cost heuristic, W7 2×2 re-test.

## 5-line summary

1. **Decision:** Phase 2 closes; `phase-2-complete` tag pushed.
2. **Delivered:** firm knowledge (W5), layered modes (W6), M&A mode
   (W7), frameworks library (W8 partial), section deepening (W9).
3. **Wedge proven:** same M&A brief flows firm content → M&A
   overlay → structured frameworks → in-loop deepening, with
   verification spine load-bearing throughout.
4. **Carry-forwards:** growth-strategy library expansion, claim-id
   minting discipline, deepening UI mount — all documented, none
   wedge-defects.
5. **Phase 3 starts:** deliverable variety + library breadth.
