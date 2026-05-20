# Phase 3 — Close

**Status:** complete (tag: `phase-3-complete`)
**Closed:** 2026-05-20
**Branch:** `phase-3/week-14` (5 commits across W14)

> Phase 3 set out to take the verified-claim base Phase 2 shipped and
> turn it into a full client-facing deliverable suite — six artifacts
> per engagement, mode-aware, firm-branded, citation-traceable, all
> rendered from one shared payload. As of Day 5 the suite works
> end-to-end across both consulting modes (M&A diligence +
> growth_strategy), the regression check holds (8/8 headline
> assertions), and the sample workspace seeder + library hardening
> give Phase 4 a known-good foundation.

## What Phase 3 delivered

- **Week 10 — Export pipeline + 1-pager** ✅
  Artifact architecture: `export_artifacts` table (migration 033),
  exporter registry + ABC + result dataclass, generate-artifact
  service, four `/api/sessions/{id}/exports` endpoints, on-disk file
  storage partitioned by `<firm>/<session>/<artifact>.<format>`.
  1-pager in HTML + PDF, mode-aware (M&A valuation row vs growth
  top-competitive-force row), firm-branded via CSS variables,
  single-page enforced via truncate-and-retry + loud-fail on
  overflow.
  [docs/eval/week10_one_pager.md](week10_one_pager.md)

- **Week 11 — Deck (PPTX)** ✅
  Mode-aware sequence dispatch: 11-slide M&A deck (title →
  exec_summary → target_overview → financial_profile →
  valuation_range → 2×2 visual → risks_matrix → integration_plan →
  recommendation → next_steps → sources); 9-slide growth deck
  (title → exec_summary → context → market_landscape →
  porters_five_forces_visual → recommendation → risks_matrix →
  next_steps → sources). Firm-branded title bar + footer + page
  number on every content slide. Per-slide citation footnotes
  mapped from a deck-wide chip registry. Logo embed via 24h asset
  cache + Pillow resize. 12-slide cap with truncate-and-retry.
  [docs/eval/week11_deck.md](week11_deck.md)

- **Week 12 — Excel financial model** ✅
  Mode-aware sheet sequence: 10-sheet M&A workbook (Cover →
  Summary → Assumptions → Revenue Build → Cost Build → Working
  Capital → DCF → Comparables → Sensitivity → Synergies); 5-sheet
  growth workbook (Cover → Summary → Assumptions → Revenue Build
  → Cost Build). Cross-sheet formulas through a shared cell
  registry (changing WACC re-computes every DCF discount factor).
  Industry-standard colour discipline (blue-on-yellow input cells,
  black formulas, green cross-sheet links). Citation comments on
  every payload-derived cell. Audit returns empty `missing` on
  both modes. 100% portable formula syntax (only `SUM` / `AVERAGE`
  / `MAX` / `MIN` / `MEDIAN`) — files evaluate identically in Excel
  and LibreOffice.
  [docs/eval/week12_excel_model.md](week12_excel_model.md)

- **Week 13 — Email + interview guide** ✅
  Cover email (markdown / HTML / PDF): mode-aware lede +
  recommendation + critical-caveat paragraphs, attachment-bundle-
  aware (the email references the artifacts that actually exist
  for the engagement and flags stale ones via a SHA-256 payload
  fingerprint diff), capped at 250 words in the body, no inline
  citation markers, firm-branded HTML with no embedded image
  (mail-client-safe). Interview guide (markdown / HTML / PDF):
  three sections (A — gap-report-driven critical evidence
  questions; B — recommendation pressure-test with claim_id
  inline markers; C — mode-specific deep-dive), capped at 15
  questions, prioritised + time-estimated, multi-page PDF with
  running header + footer + page-break-driven section transitions.
  [docs/eval/week13_email_interview_guide.md](week13_email_interview_guide.md)

- **Week 14 — Close + hardening** ✅
  - W14/D1: closed the W8 Run B writer-truncation carry-forward
    via `model_overrides.writer.model: openai/gpt-4o` +
    `max_tokens: 16000` on `growth_strategy` in
    `consulting_modes.yaml`. Writer no longer truncates on Sonnet
    4.5's 8192 default. A second-layer schema-enforcement gap
    surfaced behind the fix (gpt-4o legitimately emits
    `frameworks: null` because `GeneralReportPayload.frameworks`
    is `Optional`); bounded Path B deferred to Phase 4.
  - W14/D2: library ingestion hardened — per-file error isolation,
    structured `IngestionResult`, content-type router (PDF /
    DOCX / MD / TXT / CSV), sentence-aware chunker with table
    preservation + 200-char overlap, bulk CLI, 6-fixture content
    expansion.
  - W14/D3: sample workspace seeder — "Meridian Advisory" with 3
    users + branded chrome + expanded library + 2 cached
    engagements (M&A Kestrel Logistics + growth Halcyon Health)
    + per-engagement six-artifact bundle. Caching makes re-runs
    near-free ($0.00 LLM cost, ~35 seconds).
  - W14/D4: full six-artifact regression across both modes —
    20 artifact-format combinations, 14 ready + 6 PDFs gracefully
    skipped on Windows hosts without WeasyPrint, 8/8 headline
    assertions PASS, cross-artifact verdict consistency holds
    (M&A: `proceed_with_conditions`; growth: `expand_into:scotland`).
    [docs/eval/phase3_regression.md](phase3_regression.md)

## Phase 3 wedge demonstrated

A consultant runs Argus once. They get the full deliverable suite:

1. A **sourced memo** — the verified-claim base every other artifact
   renders from
2. An **executive 1-pager** (HTML + PDF) — colour-coded recommendation
   panel, top-3 reasons/risks, mode-specific data row, numbered
   citation chips
3. A **consulting deck** (PPTX) — mode-aware structure, firm-branded,
   per-slide citation footnotes
4. A **financial model** (XLSX) — DCF / comparables / sensitivity /
   synergies for M&A; mode-aware sheet sequence; every payload-
   derived cell cited via an openpyxl comment
5. A **client cover email** (md / HTML / PDF) — attachment-bundle-
   aware, mail-client-safe, capped at 250 words
6. An **expert-validation interview guide** (md / HTML / PDF) — gap-
   report-driven critical questions + recommendation pressure-test
   + mode-specific deep-dive

All six share one verified-claim payload. Cross-artifact verdict
consistency is verified (`tools/check_artifact_consistency.py`).
Cross-mode contamination is checked and absent. Citation completeness
is enforced at the engagement-aggregate level (≥5 distinct claim_ids
per engagement; both demo engagements clear that with 8–9).

## Carry-forwards into Phase 4 / 5

| Carry-forward | Where it stays open | Why deferred |
|---|---|---|
| **Growth Porter's via live LLM pipeline** — gpt-4o swap closes writer-truncation but `GeneralReportPayload.frameworks` is `Optional`, so the model legitimately emits `null`. The seed fixture ships a hand-curated Porter's payload to demonstrate the end-state. | Phase 4 | Needs a `GrowthStrategyReportPayload` Pydantic subclass with non-nullable `porters_five_forces`, OR a two-pass framework writer behind a `requires_two_pass_writer` mode flag. Half-day to full-day; mirrors the W7 M&A pattern + the W9 section-deepening shape. Plan in [week8_frameworks.md](week8_frameworks.md) "W14/D1 update". |
| **Companies House TIFF / OCR for scanned-PDF retrieval** | Phase 5 | OCR is a separate rabbit hole; not in scope until a customer paying for it asks. |
| **Multi-instance cache invalidation** for the W11 logo asset cache + the W13 attachment-bundle stale-flag fingerprint cache | Phase 5 | Single-node deploy today; needed before multi-node. |
| **Live Excel DATA TABLE for the sensitivity sheet** (currently statically pre-computed) | Phase 3+ if customers ask | openpyxl can't write the native DATA TABLE structure; xlsxwriter could. Pragmatic gap. |
| **SMTP send for cover email** | Phase 4+ if customers ask | Email is export-only today; sending happens in the consultant's mail client. |
| **Multi-language template support** (all templates English-only) | Phase 5 | Wait for an international firm to commit. |
| **Interview-guide Section B's dict-shape-only claim extraction** — plain-string reasons / risks land Section B at zero claim citations | Phase 4 | Standardise the writer-schema reasons / risks shape across modes so every artifact's Section-B-equivalent surfaces the same claim ids. Roll into the schema-enforcement work above. |
| **Writer payload double-encoding (historical bug)** — some `reports.key_reasons` / `risks` rows were stored as `json.dumps(json.dumps([...]))`. The W13/D5 decoder tolerates one layer of wrap. | Phase 4 | Fix the writer-side persistence path so new rows store the canonical single-encoded jsonb shape; remove the workaround. |

## Phase 4 readiness assessment

Phase 4 = the human-in-the-loop / collaboration overhaul. Detailed
scope at [docs/roadmap/phase4_scope.md](../roadmap/phase4_scope.md);
short readiness check here:

| Foundation | Status | Notes |
|---|---|---|
| Multi-user firms | ✅ | Week 5 firm-multitenancy schema (migration 024). |
| Firm-membership roles (`admin` / `member`) | ✅ | Per migration 024 + W14/D3 sample workspace. |
| Engagement-membership roles (`lead` / `member`) | ✅ | Migration 013; per-session permission gating. |
| Audit log (`audit_events` table) | ✅ | Migration 021; section-deepening retire + accept actions already log here. |
| Firm-scoped library + retrieval | ✅ | Weeks 5 + 14/D2 hardening. |
| Sample workspace fixture | ✅ | Week 14/D3 Meridian Advisory: 3 users × 2 engagements × 12 artifacts × 6 library docs, cached + idempotent. |
| Section deepening with accept / reject + history | ✅ | Week 9 versioning + W14/D3 seeded deepening rows. |
| **Gap: review / approval workflow** | ❌ | Consultant drafts → partner reviews → approve / request-changes. Phase 4 build. |
| **Gap: inline commenting** on memo + artifacts | ❌ | Comment threads tied to claim_ids. Phase 4 build. |
| **Gap: engagement-level collaboration state** | ❌ | "Who's working on what / status" surface. Phase 4 build. |
| **Gap: notification system** | ❌ | Assignment / review-requested / approved. Phase 4 build. |
| **Gap: version history UI** | ❌ | Surfaces Week 9 + Week 14 deepening rows + future review-cycle revisions. Phase 4 build. |

Phase 4 starts on a solid foundation — the multi-user / multi-
engagement spine exists and works; the collaboration UI / workflow
is the build, not the underlying data model.

## Phase 3 retrospective

### What went well

- **The export-pipeline architecture generalised cleanly across four
  artifact types.** The W10 `ExporterBase` + `@register(artifact_type,
  format)` registry + on-disk storage scaffolding shipped once in
  W10/D2 and absorbed deck (W11), Excel model (W12), email (W13),
  and interview guide (W13) without any changes to the registry
  itself. Mode-aware sequence dispatch (`get_workbook_sheets_for_mode`,
  the W11 deck sequence map) is the right shape — adding a new mode
  is a YAML edit + one slide / sheet sequence.
- **Mode-awareness held end-to-end.** M&A and growth_strategy produce
  structurally distinct artifacts at every layer (analyst gates,
  writer schema, exporter sequences, framework requirements). The
  W14/D4 regression check finds zero cross-mode contamination.
- **Citation discipline scaled.** Every artifact preserves the same
  claim_id-keyed citation model. Excel comments, deck chip registry,
  email "Sources" line, interview-guide `[claim_id: …]` markers —
  all four formats surface the same underlying registry without
  inventing parallel citation schemes.
- **The cost discipline held.** Pure-template artifact generation
  costs $0.00; only fresh writer pipelines spend money. Sample
  workspace + regression are near-free to re-run, which makes the
  Phase 4 collaboration work cheap to iterate against.

### What was painful

- **The W8 Run B regression bled into Phase 3.** Closed in W10/D1
  (evidence-gate quorum fix) but a second-layer writer-truncation
  failure surfaced behind it, stayed open until W14/D1, and even
  then the W14/D1 fix surfaced a third layer (schema enforcement)
  that we deferred to Phase 4. Three layers, three weeks of
  carry-forward. The lesson: when a fix uncovers a new failure mode,
  budget for the next layer to also exist.
- **Verifier stochasticity is the gravel in the gears.** The W10/D1
  root cause was the verifier flipping between consistent claim
  assessments and an `overall: insufficient` free-form flag.
  Stochastic regressions across days made it hard to tell whether
  a change in our code or a change in the verifier's mood was the
  cause. Future: structural assertions on verifier outputs at
  test-time + checkpoint the verifier version explicitly.
- **WeasyPrint native libs on Windows.** Every PDF artifact across
  Weeks 10, 13, and 14 hit the same pango/cairo/gdk-pixbuf gap on
  the local dev box. The W14/D4 seeder + regression handle this by
  skipping cleanly with a clear status string, but the friction
  cost real time across days.
- **Payload double-encoding was a stealth bug.** A historical writer
  path stored `key_reasons` as `json.dumps(json.dumps([...]))`. The
  decoder workaround landed in W13/D5; the writer-side fix is still
  on the carry-forward list. Bugs that don't fail loudly cost more
  than bugs that crash.

### What I'd do differently

- **Earlier structural assertions on payloads.** A Pydantic-level
  per-mode payload-schema check (W14/D1 schema-enforcement gap)
  would have caught the "writer emits `frameworks: null` despite
  prompt instructions" failure mode before it consumed three days
  of carry-forward. Phase 4 starts with the
  `GrowthStrategyReportPayload` subclass on the path.
- **Cost-capped run discipline from the start.** W14/D1's "diagnose
  without spending a run" approach (statically reading
  `llm_calls.completion_tokens=8174` to confirm Sonnet's 8192 cap)
  was the right pattern — cheaper than burning $0.40 on a diagnose
  run. Should have been the default across Phase 3, not the
  exception.
- **Caching engagement outputs as committed fixtures earlier.** The
  W14/D3 sample workspace seeder makes re-runs near-free; doing
  this in W10 instead of W14 would have made every subsequent
  week's demo iteration cheaper.
- **Tighter cross-artifact testing during build.** W14/D4's
  consistency check + mode-contamination assertions caught zero
  bugs because nothing was broken — but if either had run weekly
  through Phases 2-3, drift would have been caught at insertion
  time rather than at integration time.

## Tag

```
git tag phase-3-complete
git push origin phase-3-complete
```

Phase 3 complete is a milestone — **not** v1.0. v1.0 is when Phase 5
pilots validate the system with real firms on real engagements with
real client deliverables shipped to real partners. We are not there
yet.
