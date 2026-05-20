# Phase 3 — full six-artifact regression report

**Status:** ship

> Week 14 / Day 4 closes the Phase 3 deliverable promise: one
> engagement → six artifacts. The regression runs the entire export
> pipeline (1-pager / deck / Excel model / cover email / interview
> guide) against both seeded Meridian Advisory engagements
> (m_and_a_diligence + growth_strategy), exercises 20 artifact-format
> combinations, runs cross-artifact consistency on each engagement,
> and confirms mode-correctness end-to-end. **All 8 headline
> assertions PASS.** Cross-artifact verdict consistency holds (M&A:
> `proceed_with_conditions`, growth: `expand_into:scotland`). Growth
> Porter's renders real content (5/5 force keywords on the deck;
> 1-pager fallback row gone).

## Headline assertions (8 / 8 PASS)

| # | Assertion | Result |
|---|---|---|
| 1 | All 20 artifact generations succeed (ready OR skipped_no_weasyprint on Windows PDF formats) | ✅ |
| 2 | Mode-aware structure with no cross-contamination | ✅ |
| 3 | Growth Porter's renders real content (deck 5/5 force keywords; 1-pager no fallback) | ✅ |
| 4 | Citation completeness — each engagement's distinct cited claim_ids floor ≥ 5 (M&A: 8 / growth: 9) | ✅ |
| 5 | Firm branding visible on every PPTX / XLSX / PDF | ✅ |
| 6 | Cross-artifact recommendation verdict consistency | ✅ |
| 7 | Excel citation audit clean for both engagements | ✅ |
| 8 | Total LLM cost: $0.00 (templates only; cached seeded payloads) | ✅ |

## Per-engagement, per-artifact matrix

### Kestrel Logistics — M&A diligence (mode=`m_and_a_diligence`)

| artifact_type | format | status | size | wall |
|---|---|---|---|---|
| one_pager | html | ready | 8.8 KB | 0.40 s |
| one_pager | pdf  | skipped_no_weasyprint | — | — |
| deck | pptx | ready | 52.6 KB | 0.49 s |
| excel_model | xlsx | ready | 28.5 KB | 0.58 s |
| email | md | ready | 1.5 KB | 0.47 s |
| email | html | ready | 3.4 KB | 0.43 s |
| email | pdf | skipped_no_weasyprint | — | — |
| interview_guide | md | ready | 7.1 KB | 0.38 s |
| interview_guide | html | ready | 10.8 KB | 0.41 s |
| interview_guide | pdf | skipped_no_weasyprint | — | — |

**Recommendation extract (canonical verdict):** `proceed_with_conditions`
**Distinct cited claim_ids:** 8 (`claim_dissynergy_1`, `claim_ebitda_1`,
`claim_revenue_1`, `claim_synergy_cost_1`, `claim_synergy_cost_2`,
`claim_synergy_rev_1`, `claim_tsa_1`, `claim_walkaway_1`)

### Halcyon Health Group — UK SaaS expansion (mode=`growth_strategy`)

| artifact_type | format | status | size | wall |
|---|---|---|---|---|
| one_pager | html | ready | 9.3 KB | 0.42 s |
| one_pager | pdf | skipped_no_weasyprint | — | — |
| deck | pptx | ready | 45.0 KB | 0.47 s |
| excel_model | xlsx | ready | 13.9 KB | 0.56 s |
| email | md | ready | 1.5 KB | 0.45 s |
| email | html | ready | 3.3 KB | 0.54 s |
| email | pdf | skipped_no_weasyprint | — | — |
| interview_guide | md | ready | 7.3 KB | 0.40 s |
| interview_guide | html | ready | 10.9 KB | 0.40 s |
| interview_guide | pdf | skipped_no_weasyprint | — | — |

**Recommendation extract (canonical verdict):** `expand_into:scotland`
**Distinct cited claim_ids:** 9 (`claim_addressable_1`,
`claim_capability_1`, `claim_competitor_share_1`, `claim_entrant_1`,
`claim_entrant_2`, `claim_infrastructure_1`, `claim_pricing_1`,
`claim_procurement_1`, `claim_substitute_1`)

## Cross-artifact consistency check

`tools/check_artifact_consistency.py` extracts the recommendation
from each artifact format and normalises it to a canonical verdict
token. The verdict comparison is intentionally insensitive to:

- **Markdown emphasis markers** (`**…**`)
- **Surrounding detail** that differs between artifacts (deck
  title-bar truncates; email lede paraphrases)
- **Whitespace + casing**

Verdict patterns recognised: `proceed_with_conditions`, `proceed`,
`walk_away`, `reject`, `renegotiate`, `expand_into:<geography>`,
`expand`, `defer`, `wait_and_watch`.

Per-engagement result:

| Engagement | Distinct verdicts found | Consistent? |
|---|---|---|
| Kestrel Logistics — M&A diligence | `['proceed_with_conditions']` | ✅ |
| Halcyon Health Group — UK SaaS expansion | `['expand_into:scotland']` | ✅ |

## Mode-aware contamination check

Each artifact body is scanned for markers from the OTHER mode. M&A
artifacts must not contain Porter's content; growth artifacts must
not contain valuation/synergy content.

| Engagement | Leaked markers from other mode |
|---|---|
| Kestrel Logistics — M&A diligence | (none) |
| Halcyon Health Group — UK SaaS expansion | (none) |

## What works

- **The full pipeline holds across modes.** 14 ready artifacts + 6
  PDFs gracefully skipped on the Windows dev host where WeasyPrint's
  native libs aren't installable. In Docker / Linux production, every
  PDF format also lands ready (W13/D5 demonstrated this in the worker
  container).
- **W14/D1 fix propagated.** The growth Porter's content now lands
  end-to-end: the deck renders 5/5 force keywords (`rivalry`,
  `supplier`, `buyer`, `substitute`, `entrant`), the 1-pager top-
  competitive-force row carries real content (no "not produced for
  this engagement" fallback), and the consulting_payload
  `frameworks.porters_five_forces` block parses through every
  downstream renderer.
- **Cross-artifact consistency holds.** Both engagements pin a single
  verdict token across all extractable artifacts. The deck title-bar
  truncating to "PROCEED WITH CONDITIONS" doesn't trip a false
  positive against the memo's longer "PROCEED WITH CONDITIONS at a
  £215–£235m enterprise value range, anchored to a base case…"
  because the verdict-extractor compares on the canonical token only.
- **Citation completeness aggregates correctly per engagement.** The
  union of cited claim_ids across each engagement's bundle is 8 (M&A)
  / 9 (growth) — both well above the spec's 5-floor. Individual
  artifacts vary (interview-guide's Section B claim-extraction only
  fires on dict-shaped reasons/risks; the seeded fixtures' string
  reasons land Section B at 0 citations), but the engagement-level
  aggregate via metadata `cited_claim_ids` + the per-artifact floor
  catches the full picture.
- **Excel citation audit empty on both engagements.** No `missing`
  rows; the W12/D4 audit logic with the W14/D2 default-row vacuous-
  pass rule holds for both modes.
- **Mode-correctness with no cross-contamination.** Zero M&A markers
  in growth artifacts; zero growth markers in M&A artifacts. The
  consulting_payload structure holds (M&A: valuation_range,
  synergy_estimate, deal_structure_implications; growth: frameworks,
  competitive_landscape, options_matrix).
- **Zero LLM cost.** Cached payloads + template-only renders.

## What's still open

- **PDF formats on Windows dev hosts.** WeasyPrint's pango / cairo /
  gdk-pixbuf system libs aren't installable cleanly through pip — the
  6 PDF artifacts land as `skipped_no_weasyprint` on local. Docker
  worker (`argus-worker-1`) has the libs and renders them all; the
  W13/D5 wrap-up has the docker-exec recipe for a full PDF smoke. CI
  runs in Docker so this gap is dev-environment-only.
- **Growth Porter's is hand-curated in the seeded fixture.** The
  W14/D1 schema-enforcement carry-forward stays open; Phase 4 work
  ([`week8_frameworks.md`](week8_frameworks.md) "W14/D1 update")
  will make a live LLM run produce the same shape via a growth-
  specific `WriterReportPayload` subclass or a two-pass framework
  writer. The regression demonstrates the end-state.
- **Interview-guide Section B's claim-extraction is dict-shape-only.**
  When reasons / risks land as plain strings in the seeded fixtures,
  the W13/D3 builder's `_claim_ids_from_listish` extracts zero. The
  engagement-aggregate citation floor still passes because other
  artifacts (excel comments, email cited_claim_ids, deck chip
  registry) collectively cite ≥5 claims. Phase 4 polish: standardise
  reasons / risks shape across the writer schema so every artifact's
  Section-B-equivalent surfaces the same claim ids.

## Cost + timing summary

| Metric | Value |
|---|---|
| Engagements regressed | 2 |
| Artifact-format combinations exercised | 20 |
| Total `ready` artifacts | 14 |
| Total `skipped_no_weasyprint` | 6 |
| Total `failed` / `exception` | 0 |
| Wall time (local Windows) | ~9 seconds |
| LLM cost | $0.00 |

## Decision

- [x] **Phase 3 deliverable suite holds together.** The six-artifact
  promise — memo + 1-pager + deck + Excel model + cover email +
  interview guide — is live across both consulting modes. Cross-
  artifact consistency, mode-correctness, citation completeness, and
  the W14/D1 growth Porter's fix all confirmed.
- [ ] Iterate.

## Repro

```
python tools/seed_sample_workspace.py
python tools/run_phase3_regression.py
# Optional: deep-inspect one engagement's verdict consistency
python tools/check_artifact_consistency.py --session-id <session-uuid>
```

Cached payloads make both re-runs near-free ($0.00 LLM cost,
~9 seconds wall on local).
