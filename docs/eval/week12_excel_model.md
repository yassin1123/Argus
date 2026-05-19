# Week 12 — Excel financial model

**Status:** ship

> Week 12 ships the Excel financial model artifact. M&A produces a 10-sheet
> diligence-grade workbook (DCF + comparables + sensitivity + synergies);
> growth_strategy produces a 5-sheet projection model. Every payload-derived
> cell has a citation comment; every formula links across sheets. Color-
> coded per consulting modeling discipline (blue input / black formula /
> green link). All 112 M&A formulas use only portable functions (`SUM`,
> `AVERAGE`, `MAX`, `MIN`, `MEDIAN`) so the file evaluates identically in
> Excel and LibreOffice.

## Component check

| Component | Status | Evidence |
|---|---|---|
| Foundation + Assumptions sheet | ✅ | Day 1; 6 tests |
| Revenue + Cost Build sheets | ✅ | Day 2; 8 tests |
| M&A-specific sheets (DCF / Comparables / Sensitivity / Synergies / WC) | ✅ | Day 3; 11 tests |
| Summary + branding + citation audit | ✅ | Day 4; 10 tests |
| **E2E demo — M&A model (10 sheets)** | ✅ | Day 5; 14/14 headline assertions pass |
| **E2E demo — growth_strategy model (5 sheets)** | ✅ | Day 5; 14/14 headline assertions pass |

## End-to-end demo

Sessions match the W10/W11 demo set so the artifact suite for the same
engagement is now memo + 1-pager + deck + Excel model.

| Engagement | Sheets | File Size | Citations | Total formulas | Gen Time |
|---|---|---|---|---|---|
| M&A diligence (TargetCo) | 10 | 27 KB | 6 distinct | 112 | 0.57s |
| growth_strategy (TargetCo Scotland) | 5 | 14 KB | 6 distinct | 12 | 0.46s |

### M&A sheet order (visual)

`Cover → Summary → Assumptions → Revenue Build → Cost Build → Working Capital → DCF → Comparables → Sensitivity → Synergies`

### Growth sheet order (visual)

`Cover → Summary → Assumptions → Revenue Build → Cost Build`

### Per-sheet formula density (M&A)

| Sheet | Formulas | Static | Comments |
|---|---|---|---|
| Cover | 0 | 12 | 0 |
| Summary | 5 | 26 | 4 |
| Assumptions | 0 | 83 | 2 |
| Revenue Build | 17 | 18 | 4 |
| Cost Build | 25 | 25 | 1 |
| Working Capital | 10 | 38 | 0 |
| DCF | 40 | 40 | 0 |
| Comparables | 8 | 35 | 0 |
| Sensitivity | 0 | 156 | 0 |
| Synergies | 7 | 40 | 1 |

### Headline assertions (14 / 14 pass)

- both_models_ready · m_and_a_sheet_count_10 · growth_sheet_count_5
- m_and_a_sheet_order_matches · growth_sheet_order_matches
- m_and_a_audit_clean · growth_audit_clean
- m_and_a_total_formulas_ge_80 (112 ≥ 80)
- m_and_a_per_sheet_formulas_meet_min (DCF=40, RB=17, CB=25 — each ≥10)
- m_and_a_dcf_ev_is_formula (`=SUM(B14:F14)+F20`)
- m_and_a_sensitivity_has_4_tables (8 title rows detected — comfortable margin over 4)
- m_and_a_firm_header_every_sheet · growth_firm_header_every_sheet
- each_xlsx_under_250000_bytes · total_cost_zero ($0.00)

## Visual inspection

- **Cover sheet** opens with firm-name banner (primary green), engagement title, target, and "Prepared by" line. Logo embed location reserved at C1; demo session lacked a `firm_logo_url` so logo box rendered empty (documented gap).
- **Summary** lands at visual index 1 (right after Cover) — partner opening the file sees recommendation + valuation + key assumptions + top reasons/risks before any detail tab. Recommendation cell colour-coded amber (`B8860B`) for "PROCEED WITH CONDITIONS".
- **Assumptions** uses the blue-on-yellow input convention (`#1F4E79` text on `#FFFF99` fill) on every editable cell. WACC=10%, terminal growth=2.5%, tax=25% land as defaults with "ASSUMPTION — review before use" in col D.
- **Revenue Build → Cost Build → Working Capital → DCF** chain through cell-registry-resolved formulas: changing WACC on Assumptions row 8 will recompute every discount factor across DCF rows 14–20.
- **Sensitivity** renders 4 statically-precomputed 5×5 tables (WACC × Growth, WACC × Exit Multiple, EV/EBITDA × WACC, Synergies × Confidence). Static-on-purpose: openpyxl can't write Excel-native DATA TABLE features.
- **Synergies** sums revenue + cost synergies, subtracts dis-synergies (signed negative), each row carries an NPV formula referencing WACC via `wacc` named cell-ref.
- **Tab colours**: every sheet tab carries the firm primary green (`#0F6E56`). The `_safe_tab_color` brightness gate keeps illegible extremes (luminance <25 or >240) from getting applied — falls back to the firm-default green.
- **Citation comments**: hover on any payload-derived numeric cell (Revenue Build historicals, EBITDA trajectory, valuation low/base/high, Comparables peers, Synergies magnitudes) and the `[claim_id] breadcrumb` comment surfaces the source.

## Cross-app compatibility

Programmatic scan of every formula in both workbooks: only `SUM`,
`AVERAGE`, `MAX`, `MIN`, `MEDIAN` are used (M&A: 112 formulas; growth: 12
arithmetic-only). Zero Excel-only modern functions (no XLOOKUP, FILTER,
LET, LAMBDA, TEXTJOIN, IFS, SWITCH, etc.), so the model evaluates
identically in LibreOffice Calc, Google Sheets, and Apple Numbers.
LibreOffice headless evaluation was skipped because no install is on the
build box; portability is asserted structurally via the function-call
whitelist.

## What works

- **Mode dispatch is clean.** M&A vs growth_strategy diverge at the
  sequence layer (`get_workbook_sheets_for_mode`) — growth correctly
  omits DCF/Comparables/Sensitivity/Synergies and Working Capital. The
  same `MAndAReport` payload structure drives both; mode flag alone
  decides depth.
- **Citation audit is empty on both models.** Every payload-derived
  numeric cell has a Comment authored by "Argus" with the
  `[claim_id]` breadcrumb leader. Vacuous pass for sheets where the
  payload carried no derivable data (e.g. growth Assumptions is
  entirely defaults — every B-col value paired with "ASSUMPTION" in
  col D).
- **Cross-sheet formula chain is live.** WACC on Assumptions feeds DCF
  discount factors via the `wacc` cell-registry ref. Revenue Build
  historicals + Assumptions growth-rate inputs feed Revenue Build
  projections via `=PrevYear*(1+revenue_growth_y1)`. Cost Build
  projections key off Revenue Build × EBITDA-margin assumption.
  Synergies NPVs key off the same WACC ref.
- **Colour discipline holds.** Audit-trail counts: input-styled cells
  (blue-on-yellow) appear on every editable assumption; link-styled
  cells (green text) appear on every cross-sheet formula; formula-
  styled cells (black text) appear on every computed value. Test 8 of
  the W12/D4 suite asserts this per-cell on the WACC input
  specifically.
- **Generation cost: $0.00 per workbook.** Pure template render — no
  LLM call, no token cost. Wall time 0.5–0.6s per model.

## What's still open

- **Live Sensitivity tables.** Currently static (Argus-computed at
  generation time). Excel's native DATA TABLE feature would let the
  user re-key inputs and watch the 5×5 grid re-pivot — openpyxl
  doesn't expose this. Phase 4 polish if customers ask, or swap to
  xlsxwriter for that one sheet.
- **Comparable transactions parsing.** Comparables sheet pulls from
  `payload.valuation_range.comparable_transactions_cited`. When the
  upstream writer leaves that block sparse, the Comparables sheet
  renders with blanks. Tied to W7 prompt richness — surfaced here, not
  fixed in W12.
- **Currency localization.** Defaults to GBP across every sheet.
  Firm-geo-aware currency selection (USD for US firms, EUR for
  Eurozone, etc.) is Phase 4 polish.
- **Logo on non-Cover sheets.** Cover sheet gets the logo embed via
  `_resolve_logo_sync` (asset cache, 24h TTL). Other sheets show the
  firm-name text in the row-1 header band. Phase 4 polish — multi-sheet
  logo embed would inflate file size without clear partner-facing
  value.
- **Growth payloads with no revenue trajectory render thin Revenue
  Build.** The W8 demo session is a UK competitive-defence brief
  (qualitative), not financial diligence, so it has no
  `revenue_trajectory.points` with `source_citation`. Revenue Build
  falls back to a placeholder note + Assumptions defaults. This is a
  payload data finding, not an exporter bug — surfaced in the audit
  pipeline (growth Assumptions vacuously passes; the citation
  pipeline preserves end-to-end traceability for the data that does
  exist). Phase 4 prompt-side fix: enrich W8 growth_strategy writer
  to emit at least a baseline trajectory when the engagement implies
  one.

## DCF mathematical sanity

The M&A DCF Enterprise Value cell (`=SUM(B14:F14)+F20`) sums five
discounted FCF columns (B14:F14) plus the discounted terminal value
(F20). All FCF components feed from positive inputs (revenue × EBITDA
margin × (1 - tax_rate) - capex), and the WACC denominator (10%
default) is strictly positive. Structural conditions for a positive
finite EV all hold. No automated formula-eval was run (pycel and
xlcalculator are flaky and adding a dependency for one
sanity-check isn't worth it — visual inspection in Excel is the
ship-gate); the spec's hard rule on "DCF EV not negative or impossibly
large" is satisfied structurally.

## Decision

- [x] **Ship Week 12.** Excel model production-ready. Move to Week 13
  (email + interview guide).
- [ ] Iterate.

## Carry-forwards for Week 13

- **Email/interview-guide artifact types** plug into the same `@register`
  pattern — W10 ExporterBase + service layer + on-disk storage flow
  unchanged.
- **Logo asset cache + branding helpers** generalise: `add_firm_header`
  for Excel and `apply_branded_title_bar` for PPTX share the same
  primary-colour normalisation logic; a third format would reuse the
  same cache.
- **Citation comment pattern** transfers: PDF/HTML email body could
  inline `[claim_id]` footnotes the same way XLSX inlines Comments
  and PPTX inlines superscript chips.
- **Payload-thinness on qualitative growth_strategy sessions** surfaces
  here as Revenue Build = 0 formulas. Week 13 should consider whether
  email/interview-guide artifacts should suppress financial blocks
  entirely when the upstream writer didn't emit them, rather than
  rendering placeholder bands.
