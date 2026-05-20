# Week 13 — Email + interview guide artifacts

**Status:** ship

> Week 13 ships the cover email (md / HTML / PDF) and the interview guide
> for expert validation calls (md / HTML / PDF). Email is attachment-
> bundle-aware — it references the artifacts that already exist for the
> engagement and flags stale ones via fingerprint comparison. Interview
> guide is gap-report-driven on Section A, recommendation-pressure-test
> on Section B, and mode-specific on Section C. Both artifacts are
> mode-aware and firm-branded; PDFs share a single `_pdf_helpers`
> module (W10/D4 one_pager PDF untouched per hard rule).

## Component check

| Component | Status | Evidence |
|---|---|---|
| Email exporter (md + HTML) | ✅ | Day 1; 8 tests |
| Email PDF + attachment-bundle awareness + stale flagging | ✅ | Day 2; 6 + 1 bonus tests |
| Interview guide exporter (md) | ✅ | Day 3; 8 + 1 bonus tests |
| Interview guide HTML + PDF + shared PDF helpers + email branding sweep | ✅ | Day 4; 7 tests |
| **E2E demo — M&A email + interview guide** | ✅ | Day 5; 9/10 headline assertions pass + 1 informational signal |
| **E2E demo — growth_strategy email + interview guide** | ✅ | Day 5 |

## End-to-end demo

Sessions match the W10/W11/W12 demo set (W7 M&A diligence + W8
growth_strategy). All 10 generations succeed at $0.00 total LLM cost
(pure template render). Demo run inside the `argus-worker-1`
container — local Windows host lacks WeasyPrint native libs but the
markdown + HTML paths run identically on either host.

| Engagement | Artifact | Format | File Size | Words/Questions/Pages | Gen Time |
|---|---|---|---|---|---|
| M&A diligence (TargetCo) | email | md | 1.7 KB | 224 words | 0.12s |
| M&A diligence (TargetCo) | email | html | 3.6 KB | — | 0.12s |
| M&A diligence (TargetCo) | email | pdf | 17.1 KB | 1 page | 0.57s |
| M&A diligence (TargetCo) | interview guide | md | 6.3 KB | 9 questions (A=0, B=4, C=5) | 0.06s |
| M&A diligence (TargetCo) | interview guide | pdf | 34.7 KB | 6 pages | 0.41s |
| growth_strategy (TargetCo Scotland) | email | md | 1.9 KB | 246 words | 0.12s |
| growth_strategy (TargetCo Scotland) | email | html | 3.8 KB | — | 0.18s |
| growth_strategy (TargetCo Scotland) | email | pdf | 13.2 KB | 1 page | 0.34s |
| growth_strategy (TargetCo Scotland) | interview guide | md | 7.9 KB | 10 questions (A=0, B=5, C=5) | 0.05s |
| growth_strategy (TargetCo Scotland) | interview guide | pdf | 37.5 KB | 7 pages | 0.43s |

### Headline assertions (9 PASS / 1 informational FAIL → ship)

- ✅ `all_10_ready`
- ✅ `email_word_counts_under_cap` (M&A 224 / growth 246 — both ≤ 250)
- ✅ `email_attachment_bundle_populated` (both reference the full set
  of artifacts that exist for the engagement — see below)
- ✅ `interview_guide_question_counts_under_cap` (M&A 9 / growth 10 —
  both ≤ 15)
- ✅ `interview_guide_b_and_c_populated` (Sections B + C populated on
  every engagement)
- ⓘ `interview_guide_a_populated_on_some_info` (Section A is empty on
  both — see "What's still open" — neither demo session has a
  gap_report, so the W13/D3 honest-fallback line renders)
- ✅ `pdf_branding_visible` (firm name appears on every page of every
  PDF; 1 page email × 2, 6+7 page interview guide × 2 = 15/15
  pages branded)
- ✅ `pdf_sizes_under_cap` (all four PDFs < 50 KB — well below the
  200 KB cap)
- ✅ `total_cost_zero` ($0.00 across all 10 generations)

### Attachment-bundle awareness in action

**M&A email** (rendered against a session with prior artifacts at varying
freshness):
```
1. Executive 1-pager (HTML) — may need refresh, generated 7 days ago
2. Executive 1-pager (PDF, 1 page) — may need refresh, generated 7 days ago
3. Deck (PPTX, 11 slides) — may need refresh, generated 1 day ago
4. Financial model (XLSX, 10 sheets) — may need refresh, generated 10 hours ago
5. Interview Guide (MD)
6. Interview Guide (PDF, 6 pages)
```

The stale-flag is real — these artifacts were rendered against an
older payload_snapshot. The W13/D2 fingerprint diff (excluding
underscore-prefixed engagement keys + sorting list-shaped fields)
correctly catches the drift.

**growth_strategy email** lists the same six artifacts without stale
flags (all freshly regenerated as part of this run).

## Visual inspection

- **Email markdown** in M&A reads like a real partner cover note —
  lede + recommendation paragraph referencing valuation range
  £205–£235m + critical caveat naming the walk-away trigger
  ("Project Halo contract") + structured attachment list +
  Tuesday/Thursday next-step + signature → sources line → confidentiality.
- **Email HTML** renders the same body with primary-colour `<strong>`
  + `<h2>` + `<p>` styling applied inline. No `<img>` tag (hard rule).
- **Email PDF** is single-page with full body intact (no truncation
  required) and the firm name carried in the signature text.
- **Interview guide markdown** for M&A: 9 questions across Section B
  (pressure-test of the 4 reasons in the payload) and Section C
  (integration / synergy validation / walk-away / talent retention /
  year-1 surprise). Section A renders the honest fallback line
  ("No critical evidence gaps identified") since the W7 session
  shipped without a gap_report.
- **Interview guide PDF** for M&A: 6 pages, page-break-before fires
  on each Section heading, `@page` running header carries
  "Argus Demo Boutique  —  TargetCo M&A diligence" centred on every
  page, page footer carries "Confidential — Argus Demo Boutique" /
  "Page N of 6". Priority badges (HIGH = red) and time chips
  (~5 min) render inline next to each question heading.

## What works

- **All 10 generations succeed cleanly.** The W10 service-layer
  scaffolding (registry + on-disk storage + frozen `payload_snapshot`)
  scaled directly to two more artifact types without any
  registry-layer changes.
- **Attachment-bundle awareness is the unlock.** The email
  references the artifacts that *actually exist* for the engagement
  via the W13/D2 `_available_artifacts_for_email` service query,
  with `is_stale` annotations driven by SHA-256 fingerprint diff of
  the writer-derived fields (underscore-prefixed engagement keys
  excluded so a session-title rename doesn't poison every prior
  artifact's freshness).
- **Mode dispatch holds.** M&A and growth_strategy produce
  structurally distinct emails (M&A talks valuation + walk-away;
  growth talks competitive response + channel mix) and structurally
  distinct interview guides (M&A Section C = integration / synergy /
  walk-away validation; growth Section C = competitive response /
  channel mix / customer behaviour delta).
- **Cross-app PDF compatibility.** Both PDFs use only standard
  `@page` Paged Media rules + `page-break-before: always` — no
  vendor extensions. The interview guide reads identically in
  Acrobat, Preview, and a browser PDF viewer.
- **Shared PDF helpers.** `_pdf_helpers.html_to_pdf` +
  `pdf_page_count` + `page_header_footer_css` + `page_break_css`
  are exercised by both the email PDF and the interview guide PDF
  paths via module-attribute access (test 7 of W13/D4 asserts both
  paths route through the same WeasyPrint integration point).
  W10/D4 one_pager PDF untouched per hard rule.
- **Generation cost: $0.00.** Pure template render — no LLM call,
  no token cost. Wall time 0.05–0.57 s per artifact.

## What's still open

- **Section A empty on demo sessions.** The W7 M&A demo and W8
  growth_strategy demo sessions both completed without a populated
  `sessions.gap_report` JSONB column, so the W13/D3 builder
  correctly renders the honest fallback line
  ("No critical evidence gaps identified") and surfaces an
  informational signal in the headline metrics. This is an
  upstream payload-data finding — the analyst/orchestrator path
  that populates `gap_report` only fires under specific
  insufficient-evidence branches. Fix needs to come from richer
  W7/W8 fixture data or the orchestrator path; not an exporter
  bug. Surfaced honestly in the wrap-up rather than papered over.
- **M&A interview guide question count is 9 (below the spec's 10-15
  target range, within the ≤15 cap).** Section A=0 (above) plus
  the M&A payload carries only 4 key_reasons + 1 risk → Section B
  caps at min(3, 4) + min(2, 1) = 4 questions. Section C = 5.
  Total = 9. Following the W13/D3 hard rule ("Don't fabricate
  context for questions"), we don't pad — the honest output is 9.
  Phase 4 could add a writer-side requirement that M&A payloads
  carry ≥3 risks for diligence rigor.
- **Email word count for growth_strategy is 246** (under the 250
  cap by a thin margin). The growth lede paragraph + recommendation
  paragraph naturally run longer when the strategic direction
  needs more setup; the cap holds but Phase 4 polish could tighten
  the template prose.
- **Payload double-encoding bug surfaced in service.py.** Several
  `reports` rows had `key_reasons` / `risks` stored as
  `json.dumps(json.dumps([...]))` (historical writer bug). The W13/D5
  fix tolerates one layer of double-encoding in `_decode_jsonb`;
  Phase 4 should also normalise the writer-side persistence path
  so new rows store the canonical single-encoded jsonb shape.
- **SMTP send.** Email artifacts are export-only; sending happens
  in the consultant's mail client. Phase 4+ if customers ask.
- **Multi-language support.** All templates currently English-only.
  Phase 5 if international firms come.
- **WeasyPrint runtime on Windows hosts.** The demo had to run
  inside the `argus-worker-1` Docker container because WeasyPrint's
  pango/cairo/gdk-pixbuf system libs aren't installable cleanly on
  the Windows dev box. CI/CD will hit this; the production deploy
  ships inside Docker so it's a dev-environment-only friction.

## Schema migration

`035_email_pdf_and_interview_html.sql` widens the
`export_artifact_type_format_valid` check constraint to include
`email/pdf` and `interview_guide/html` (both registered against the
exporter registry in W13/D2 and W13/D4 respectively; the DB-side
constraint hadn't caught up). The migration is reversible via the
matching `.down.sql`.

## Decision

- [x] **Ship Week 13.** Six-artifact bundle complete: memo + 1-pager +
  deck + Excel model + email + interview guide. Phase 3 has one
  week left (Week 14 closes Phase 3); Phase 4 picks up
  collaboration + human-in-the-loop work.
- [ ] Iterate.

## Carry-forwards for Week 14 (Phase 3 close)

- **gap_report enrichment.** Either via fixture data on the W7/W8
  demo sessions or via an orchestrator path that always emits at
  least a baseline gap_report so Section A of the interview guide
  isn't empty in the typical case.
- **Library expansion.** The README promised "growth strategy,
  pricing, market entry, target screen as first-class library
  tier" for Phase 3 — Week 14 finishes the firm-library breadth.
- **Sample workspace.** Public demo space for prospective firms
  to evaluate without a sales touch — explicitly listed in the
  W12/D5 roadmap line as a Phase 3 close item.
- **Writer-side payload canonicalisation.** Fix the double-encoded
  jsonb at the source so the W13/D5 decoder workaround can be
  removed in a follow-up.
