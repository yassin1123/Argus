# Week 5 — Firm library

**Status:** ship

## Component check

| Component | Status | Evidence |
|---|---|---|
| Backend ingestion service | ✅ | Day 1; firms / firm_memberships / firm_content + chunk-scope migration; `core/firm_library/service.py`; PDF + DOCX + MD/TXT idempotent on `(firm_id, sha256)` |
| Upload UI | ✅ | Day 2; `/firm/library` admin-only upload with title + category + description + intended-modes + sector-tags; Vitest+RTL suite green |
| Browse + retire + permissions | ✅ | Day 3; admin/member role gating; cross-firm reads return 404 (not 403) to prevent enumeration; domain-rich `audit_events` on every state change |
| Retrieval integration | ✅ | Day 4; orchestrator expands `"uploaded"` → `["uploaded", "firm_library"]`; firm-library chunks emit `source_type='firm_library'` with breadcrumb `metadata` jsonb (firm_content_id, title, category, intended_modes, sector_tags, section) |
| Citation breadcrumbs | ✅ | Day 4; popover renders "📚 Firm Library — {title} ({category})" with section subline; `inferTrustTier` maps firm_library → "firm" tier |
| Source diversity | ✅ | Day 4; `firm_library` is its own bucket in `core/firm_library/diversity.py`, alongside sec_filings / transcripts / news / ch_filings |

## End-to-end demo

Demo firm: **Argus Demo Boutique** with the four synthetic fixtures
seeded by `tools/seed_week5_demo.py` (4 firm_content rows / 25
firm_library chunks). Baseline firm: **Argus Baseline Firm** with
zero library content. All three runs executed via
`tools/run_week5_e2e.py` with `ARGUS_USE_ENSEMBLE_VERDICT=true`.

### Engagement A — M&A target screen

> Brief: "Generate a target screen for a UK retail-sector acquisition
> target with €100–500M revenue. Focus on omnichannel readiness and
> operational efficiency."

| Metric | With library | Baseline (no library) |
|---|---|---|
| Total claims / grounded | 20 / 12 | 0 / 0 (no report — pipeline returned `insufficient`) |
| Library-grounded claims | 12 / 12 (100% of grounded) | n/a |
| Firm-library citations | **17 chunks across 2 distinct items** | 0 |
| Items cited | Retail Sector Primer (16), M&A Target Screen Playbook (1) | n/a |
| Recommendation specificity (numeric / time-bound) | 7 / 2 | 0 / 0 |
| References playbook methodology | yes (verbatim phrasing) | n/a |
| Wall (s) / Cost ($) | 665.3 / 0.5380 | 312.2 / 0.2276 |

### Engagement B — Growth strategy

> Brief: "Develop a 3-year growth strategy for a regional UK retailer
> entering the US market. Cover entry mode options, market
> attractiveness, and risk profile."

| Metric | With library |
|---|---|
| Total claims / grounded | 21 / 13 |
| Library-grounded claims | 13 / 13 (100% of grounded) |
| Firm-library citations | **23 chunks across all 4 distinct items** |
| Items cited | Retail Sector Primer (17), M&A Target Screen Playbook (3), Valuation Methodology (2), Growth Strategy Framework (1) |
| Recommendation specificity (numeric / time-bound) | 17 / 2 |
| Wall (s) / Cost ($) | 587.5 / 0.5246 |

(Brief B was not run on the baseline firm; the A baseline already
demonstrates the no-library terminal state.)

## Did the library visibly shape output?

Yes. Both with-library recommendations contain phrasing and decision
criteria lifted directly from the seeded fixtures. The baseline run
returned no report at all — Argus's evidence-discipline path
(`evidence_insufficient`) fired because the baseline firm had no
content to ground on.

### A — with-library recommendation (excerpt)

> Accept UK retail targets in the €100–500M revenue range if they
> meet ALL of: (a) **cost-to-serve per channel** demonstrably below
> sector median with documented **channel P&L decomposition**, (b)
> **private-label program** contributing measurable gross margin
> advantage with 3-year trend data, (c) **12-month customer cohort
> retention** above sector median for last 3 cohorts with cohort-
> level data, (d) positioned as scaled omnichannel operator OR
> specialist single-channel player with named differentiation moat.
> Reject if: missing any criterion, positioned in **squeezed middle
> segment (regional chains, mid-market department stores, second-tier
> grocers)** …

The bolded phrases are direct lifts from the **Retail Sector
Primer** fixture:

- "cost-to-serve per channel" → primer's KPI section: *"diligence
  should focus less on 'do they have omnichannel' and more on
  'what is their cost-to-serve per channel'"*
- "12-month customer cohort retention" → primer's KPI list verbatim
- "squeezed middle … regional chains, mid-market department stores,
  second-tier grocers" → primer's market-structure paragraph verbatim
- "private-label program" → primer's "private label has
  re-accelerated" trend

### B — with-library recommendation (excerpt)

> Enter the US market via acquisition of a regional grocer in the
> Mid-Atlantic corridor … or Upper Midwest cluster, targeting a
> £100m–£200m revenue asset with demonstrated omnichannel capability
> (≥15% digital sales penetration, <£8 cost-to-serve for online
> orders), followed by a 12-month integration phase with **defined
> gates**: achieve baseline omnichannel KPIs within 6 months,
> implement private label program by month 9, and validate retail
> media capability by month 12 before expanding physical footprint.

The "regional grocer" framing comes from the primer's *"Grocery is
regional. There is no national-scale grocer in the US in the way
Tesco is national in the UK."* The phased gate structure matches
the **Growth Strategy Framework's** *"90-day execution roadmap …
gating decisions for the buyer's leadership team"*. Run B is the
proof that all four fixtures can co-cite in a single engagement
when the brief intersects multiple categories.

### A — baseline (no-library) outcome

No report row was written. The pipeline fired the
`evidence_insufficient` path after 5 LLM calls (analyst+critic+
verifier) and surfaced a gap report. The captured gap-report excerpt:

> "Validation of the '15-25 potential targets' estimate through even
> basic Companies House API queries or industry database samples …
> Precedent transaction data for UK mid-market retail M&A …
> Specific examples of omnichannel assessment frameworks used in
> retail due diligence …"

This is the right behaviour: with no firm-curated content and no
ingested public sources for UK retail in the dev DB, Argus refuses
to write a memo rather than fabricate one. The structural difference
between with-library (a sourced 12-grounded-claim memo) and baseline
(no memo, gap report) is the cleanest possible demonstration that
the library is binding.

## What works

- **Headline assertion passes for both engagements.** Both with-
  library runs produce ≥1 firm_library citation; A produced 17
  across 2 items, B produced 23 across all 4 items.
- **Cross-fixture citation in B.** The growth-strategy brief pulled
  from all four library categories (sector primer, M&A playbook,
  valuation methodology, growth-strategy framework) — the
  "uploaded → firm_library" routing surfaces semantically-relevant
  content, not just the most-similar single document.
- **Firm-vetted citations dominate the diversity profile** when
  firm content covers the brief. Both with-library runs show
  `firm_library` as the only citation bucket — the engagement
  uploaded path is firm-anchored end-to-end.
- **Cross-firm isolation holds end-to-end.** The baseline firm sees
  zero firm_library chunks despite having `firm_id = NOT NULL` on
  every chunks-table row; Day-1 hybrid_search firm-scoping is the
  reason this is a clean comparison rather than a leak.
- **Synthesis discipline holds.** Both with-library memos cite
  fixture phrasing verbatim where appropriate, and the baseline
  surfaces a gap report instead of fabricating numbers.

## What's still open

- **Library citations don't yet reach the PDF/DOCX export footnote
  block.** The popover renders the breadcrumb correctly in the web
  UI, but the export path still emits the raw `source_title`
  without the "📚 Firm Library — " prefix. Phase 3 export work will
  pick this up.
- **Trust-tier ranking is currently flat.** Firm-library chunks
  rank by cosine similarity alongside web content; we don't yet
  boost firm-vetted retrieval at retrieval time. The Week 6
  per-firm consulting modes work is the right place to address this
  if it becomes a real concern (today the demo did not need the
  boost — semantic match was enough).
- **Sector inference at upload time is manual.** The seeder picks
  `sector_tags` by hand; there's no automatic sector classifier on
  the upload path.
- **Live-ingest is still deferred.** Week 4 / Day 4's note about
  Companies House live-ingest still applies — Phase 3.

## Decision

- [x] **Ship Week 5.** Library lifecycle production-ready: ingest →
  browse → retire → cite end-to-end with cross-firm isolation, role
  gating, audit trail, and citation breadcrumbs. Move to Week 6
  (per-firm consulting modes).
- [ ] Iterate.

Run records:
- `backend/eval_runs/week5_e2e/A_with_library.json`
- `backend/eval_runs/week5_e2e/B_with_library.json`
- `backend/eval_runs/week5_e2e/A_no_library.json`
- `backend/eval_runs/week5_e2e/summary.json`
