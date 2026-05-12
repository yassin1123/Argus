# Week 10 — Export pipeline + 1-pager

**Status:** ship

> Phase 3 / Week 10 stands up the artifact-generation backbone (table,
> registry, service, API, file storage) and ships the first concrete
> deliverable on top of it: a mode-aware, firm-branded, citation-
> preserving 1-pager rendered in HTML and PDF. The export architecture
> is the load-bearing piece — adding deck / Excel / email /
> interview-guide in Weeks 11-13 is a registry entry per format, not
> a re-architecture.

## Component check

| Component | Status | Evidence |
|---|---|---|
| W8 regression closed (Day 1) | ✅ | Diagnosed as verifier stochastic verdict drift; gate hardened in [orchestrator.py:942-981](../../backend/agents/orchestrator.py); tag `w8-regression-fixed`. Run A now lands 7/7 on every fire. |
| Artifacts table + migration | ✅ | Day 2; `033_export_artifacts.sql` (renamed from spec's `artifacts` to avoid collision with the Phase 9 `artifacts` table — different concern, both shipped) |
| Exporter base + registry | ✅ | Day 2; `core/exports/_base.py` + `_registry.py`; 5 service tests |
| API endpoints (POST / GET / list / download) | ✅ | Day 2; `api/session_exports.py`; firm-member permissions parity with section_deepening |
| 1-pager HTML renderer (mode-aware) | ✅ | Day 3; 7 renderer tests + 2 helper sanity |
| 1-pager PDF generation (single-page) | ✅ | Day 4; 5 PDF tests + truncate-and-retry + loud-fail on overflow |
| **E2E demo — M&A 1-pager HTML** | ✅ | Day 5, this doc |
| **E2E demo — M&A 1-pager PDF** | ✅ | Day 5, this doc |
| **E2E demo — growth_strategy HTML** | ✅ | Day 5, this doc |
| **E2E demo — growth_strategy PDF** | ✅ | Day 5, this doc |

## End-to-end demo

Two real sessions from the demo firm `argus-demo-boutique`:

- M&A: [`9da8a365-...`](../../backend/eval_runs/week10_e2e/m_and_a_pdf.json) — the W7 M&A demo session (7/7 fields, 4-item 2×2, `PROCEED WITH CONDITIONS`)
- growth_strategy: [`bcb54507-...`](../../backend/eval_runs/week10_e2e/growth_pdf.json) — TargetCo Scotland-pilot growth-strategy memo (Run B from W8 — landed key_reasons/risks + recommendation; Porter's never produced because of a writer JSON-truncation bug surfaced in W10/D1)

| Engagement | Format | File Size | Citations | Pages | Gen Time |
|---|---|---|---|---|---|
| M&A diligence (TargetCo) | HTML | 7,183 B | 6 | n/a | 0.25 s |
| M&A diligence (TargetCo) | PDF | 23,296 B | 6 | 1 | 0.90 s |
| growth_strategy (TargetCo Scotland) | HTML | 12,281 B | 12 | n/a | 0.09 s |
| growth_strategy (TargetCo Scotland) | PDF | 28,251 B | 12 | 1 | 0.99 s |

Combined LLM cost across all 4 generations: **$0.00** — template rendering is pure Python; the only paid LLM call in the export pipeline is for future deck/Excel/email/interview-guide formats that may need text adaptation, which Week 11+ will introduce.

### Structural inspection (PDF text extraction)

| Marker | M&A PDF | growth PDF | Expected |
|---|---|---|---|
| Firm header (`Argus Demo Boutique`) | ✅ | ✅ | both |
| Engagement title visible | ✅ | ✅ | both |
| RECOMMENDATION label + panel | ✅ | ✅ | both |
| TOP REASONS / TOP RISKS columns | ✅ / ✅ | ✅ / ✅ | both |
| Valuation range (M&A-specific) | ✅ | ❌ | M&A only |
| Walk-away trigger (M&A-specific) | ✅ | ❌ | M&A only |
| Top competitive force (growth-specific) | ❌ | ⚠️ fallback | growth only |
| Recommendation text recognisable | "PROCEED" ✅ | "Scotland" ✅ | both |
| Numbered citation chips (`1 claim_...`) | ✅ | ✅ | both |
| Footer (`Every claim verified`) | ✅ | ✅ | both |

Mode-aware dispatch is working as designed: the M&A 1-pager omits Porter's, the growth 1-pager omits valuation. The growth Porter's row falls back to "Porter's Five Forces not produced for this engagement." because the source payload's `frameworks.porters_five_forces` block is missing — that's the W8 Run B writer-truncation carry-forward documented in [docs/eval/week8_frameworks.md](week8_frameworks.md), not a renderer defect.

## Headline assertions

| Assertion | Threshold | Result |
|---|---|---|
| All 4 generations status=ready | required | ✅ 4/4 |
| Each PDF exactly 1 page | required | ✅ M&A=1, growth=1 |
| M&A 1-pagers contain valuation numbers | required | ✅ 205 / 220 / 235 visible in HTML + PDF |
| growth 1-pagers contain top-force reference | required | ⚠️ source payload lacks frameworks block; fallback row renders correctly. Tracked as Phase 3 carry-forward (W8 Run B writer-truncation) |
| Each artifact citations ≥ 5 | required | ✅ M&A 6, growth 12 |
| Each PDF < 500 KB | required | ✅ M&A 23 KB, growth 28 KB |
| Total cost < $0.10 | required | ✅ $0.00 |

**Net: 6/7 headline assertions pass.** The single failure is a source-data gap that traces to a pre-existing Phase 2 carry-forward, not a Week 10 deliverable defect. All four artifacts generate successfully, all four are single-page, all four are branded, all four preserve citations.

## What works

- **Mode-aware section dispatch.** M&A includes valuation row + walk-away; growth_strategy includes top competitive force (or honest fallback when Porter's is absent). The dispatch is driven by `payload.mode` plus a heuristic fallback (presence of `valuation_range` / `synergy_estimate` ⇒ M&A) so missing-mode payloads still classify correctly.
- **Citation preservation across formats.** HTML uses `data-claim-id` chips with hover tooltips; PDF preserves the numbered superscripts + the chip block at the bottom. Each citation maps back to the analyst's `key_claims[].claim_id` plus the matched `evidence_objects[].source_title`.
- **Firm branding applied throughout.** CSS variables driven by `firms.branding`: `--primary`, `--secondary`, `--font-stack`, footer text, logo URL (with text fallback when empty). Demo firm primary `#0F6E56` rendered on the recommendation panel border and section headings in both formats.
- **Single-page PDF guarantee with truncation fallback.** Attempt 1 renders reasons=3 / risks=3. On overflow, attempt 2 collapses both to 2 (originally just risks per spec; reasons added during D5 because growth_strategy's verbose recommendation prose pushed past one page). If still overflowing, raises `OnePagerPdfOverflowError` with a `content_overflow_after_truncation` reason — no silent multi-page artifact.
- **Frozen point-in-time snapshots.** `export_artifacts.payload_snapshot` captures the writer payload at generation time. Re-deepening a section after export doesn't mutate the existing artifact; a new generation produces a fresh row.
- **Pure renderer.** Zero DB / network calls during render. The service layer fetches inputs (payload, branding, citations, session meta) once and hands them to `exporter.render(...)`. Tests are pure unit tests.

## What's still open

- **Porter's data gap on the growth_strategy demo session.** Not a Week 10 issue — Run B's writer JSON-truncated during W8/W10/D1 so no `frameworks` block landed. Renderer behaves correctly (shows fallback). Resolution path: fix the writer max_tokens / output-budget issue (logged in [phase2_close.md](phase2_close.md) carry-forwards). Until then, every growth_strategy 1-pager that runs on a payload missing Porter's will show the same fallback row.
- **Front-end "Export ▾" dropdown ships with HTML + PDF only.** Phase 4 polish: preview before download; format picker styling; integrating with the ArtifactsRail panel so generated artifacts surface in the workspace sidebar without manual refresh.
- **Logo image fetching is HTTP-at-render-time.** Demo firm's `logo_url` is empty so the issue doesn't surface, but firms that set a remote logo URL will pay one network round-trip per render. Phase 5 caching task.
- **Citation footnotes show source breadcrumb but not the exact passage quote.** Clicking through to source still requires the workspace view. The PDF's chip carries `data-claim-id` so a future viewer-app round-trip can fetch the underlying quote.
- **PDF text-extraction order differs from visual order.** PyMuPDF's `get_text('text')` returns content in PDF stream order, not visual top-to-bottom. The structural-inspection check works because we test for marker presence, not position. If we want pixel-accurate visual diffing later (regression detection), a render-to-PNG + perceptual hash path is the Phase 5 work.

## Decision

- [x] **Ship Week 10.** Foundation laid for Phase 3 deliverable variety. M&A 1-pager (HTML + PDF) lands cleanly on every fire; growth_strategy 1-pager lands cleanly modulo the Porter's data gap (which is upstream of the renderer). The export architecture (`export_artifacts` table, `ExporterBase` + registry, `generate_artifact()` service, 4 API endpoints, on-disk file storage) supports adding deck / Excel / email / interview-guide as registry entries in Weeks 11-13.
- [ ] ~~Iterate.~~ Closed.

**Phase 2 carry-forwards still open** (unchanged by Week 10):
- Growth-strategy writer JSON-truncation (Run B) — needs `max_tokens` bump + verify
- Deepening UI route mount (Phase 4 polish)
- Cost-cap heuristic refinement (low priority)
- W7 2×2 `min_length=4` re-test (low priority)

## Run records

- [m_and_a_html.json](../../backend/eval_runs/week10_e2e/m_and_a_html.json)
- [m_and_a_pdf.json](../../backend/eval_runs/week10_e2e/m_and_a_pdf.json)
- [growth_html.json](../../backend/eval_runs/week10_e2e/growth_html.json)
- [growth_pdf.json](../../backend/eval_runs/week10_e2e/growth_pdf.json)
- [summary.json](../../backend/eval_runs/week10_e2e/summary.json)

## 5-line summary

1. **Decision:** ship Week 10. Foundation + 1-pager (HTML + PDF) production-ready.
2. **W8 regression status:** **closed** in W10/D1 (verifier stochastic verdict drift; gate hardened with quorum check on claim_assessments). Tag `w8-regression-fixed`.
3. **1-pager looks like:** firm-branded header band; color-coded recommendation panel (amber on M&A's "PROCEED WITH CONDITIONS", neutral on growth's long-form prose); two columns of top 3 reasons / risks; mode-specific supplement row (valuation triple for M&A, top-competitive-force for growth or honest fallback); source counts + numbered citation chips with `data-claim-id`; firm footer. Single A4 page enforced via truncate-retry + loud fail.
4. **Open:** growth_strategy Porter's data gap (W8 Run B writer-truncation, upstream of renderer) — known carry-forward in Phase 2 close doc; renderer shows correct fallback.
5. **Week 11 starts with:** memo (HTML + PDF) using the same exporter scaffolding — `@register('memo', 'html')` + `@register('memo', 'pdf')` + a longer multi-section template that can run over many pages. Then deck (Week 12) and Excel + email + interview-guide (Week 13).
