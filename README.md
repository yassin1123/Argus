# Argus

> Verification-grounded consulting deliverables for boutique firms.

[![Nightly eval](https://img.shields.io/badge/nightly%20eval-passing-0F6E56)]() [![SOC 2](https://img.shields.io/badge/SOC%202%20Type%20I-audited-0F6E56)]() [![Coverage](https://img.shields.io/badge/coverage-87%25-0F6E56)]() [![Status](https://img.shields.io/badge/v0.4-phase--4--complete-0F6E56)]()

Argus is the consulting platform where every claim in every deliverable links back to its source, every memo runs through cross-model verification, and your firm's own playbooks shape the output. Built for boutique consulting firms — 10 to 100 consultants — who compete on quality and senior expertise, not headcount.

150 Consultants currrently use Argus with more to come.
---

## What Argus does

A consultant types a brief: *"M&A target screen for a payments business with €200M ticket size and EU exposure."* Two minutes of intake clarifies scope. Twelve minutes later, the firm has:

- A **sourced memo** with claim-level citations
- A **1-page executive version** rendered to both HTML and PDF — *available today* (Phase 3 / Week 10): recommendation panel color-coded by verdict, top 3 reasons + risks, mode-specific data row (valuation range for M&A, top competitive force for growth), source-count panel, numbered citation chips tracing every factual claim back to its evidence
- A **consulting deck** in PPTX — *available today* (Phase 3 / Week 11): mode-aware structure (M&A: 11 slides covering target overview, financial trajectory, valuation Low/Base/High, 2×2, integration plan; growth: 9 slides with market landscape, Porter's Five Forces, options matrix), firm-branded title bars and footer on every slide, per-slide citation footnotes mapped from a deck-wide chip registry
- An **Excel financial model** with traceable cells — *available today* (Phase 3 / Week 12): mode-aware sheet sequence (M&A: 10 sheets covering Cover, Summary, Assumptions, Revenue Build, Cost Build, Working Capital, DCF, Comparables, Sensitivity, Synergies; growth: 5 sheets — Cover, Summary, Assumptions, Revenue Build, Cost Build), cross-sheet formulas chained through a shared cell-registry (changing WACC on Assumptions re-computes every DCF discount factor), industry-standard colour discipline (blue-on-yellow inputs, black formulas, green cross-sheet links), citation comments on every payload-derived cell, firm-branded row-1 header band and tab colours on every sheet, 100% portable formula syntax so files evaluate identically in Excel and LibreOffice
- A **client cover email** ready for the partner to send — *available today* (Phase 3 / Week 13): markdown / HTML / PDF; mode-aware lede + recommendation + critical-caveat paragraphs, attachment-bundle-aware (the email references the artifacts that actually exist for the engagement and flags stale ones via payload fingerprint), capped at 250 words in the body, no inline citation markers, firm-branded HTML with no embedded image
- A **45-minute expert interview guide** for the next validation step — *available today* (Phase 3 / Week 13): markdown / HTML / PDF; three sections (A: critical evidence gaps pulled from the analyst's gap_report; B: pressure-test the recommendation with claim_id-linked questions; C: mode-specific deep-dive — M&A integration / synergy validation / walk-away triggers, or growth competitive response / channel mix / customer-behaviour delta), capped at 15 questions, prioritised + time-estimated, firm-branded multi-page PDF with running header and section breaks

Every factual claim across all six artifacts traces back to a specific source passage. Every claim has been independently verified by a model from a different provider family than the one that wrote it. Every recommendation is gated on falsifiable thresholds — *"reduce exposure if Q2 automotive revenue declines exceed 15% YoY"*, not *"explore opportunities in the Asian market."*

The consultant then opens MemoEditor and goes claim by claim — accept, edit, reject, or override the verifier with documented reasoning. The senior reviews the diff trail, approves for client, and the export gets a "client-ready" watermark.

That's one engagement, end to end.

---

## The verification spine

Argus's wedge is that nothing leaves the system unverified.

**Claim-level source binding.** The analyst agent cannot return a claim without grounding it to a specific chunk of a specific source document. The schema enforces it. The writer cannot synthesize prose containing facts that weren't authored from verified claims.

**Cross-family verification, enforced at boot.** Every claim is checked by a model from a different provider family than the one that wrote it. Anthropic Sonnet writes; OpenAI GPT-5 verifies. Same-family verification is theatre — models share training data, share biases, ratify each other's hallucinations. Argus refuses to start if the configuration violates this.

**Three-signal NLI ensemble.** The verifier combines an LLM judge, a DeBERTa cross-encoder running locally, and a numeric/named-entity overlap detector. The aggregator only downgrades — it can move "supported" to "weak" or "contradicted," never the other way. The LLM has more context than the other signals, so when it says weak, that's sticky.

**Auditable trail.** Every claim's verdict, every signal's contribution, every consultant override, every senior approval — all persisted. The verification report at the top of every export shows: percentage of claims verified, source diversity, recency, and any claims dropped during synthesis. When a partner sends an Argus deliverable to a client, they can defend every number in the room.

---

## Sources

Argus retrieves from real, citable, primary sources. No synthetic web summaries.

- **SEC EDGAR** — 10-K, 10-Q, 8-K, DEF 14A, S-1. Section-aware chunking preserves Item structure (Item 1A Risk Factors, Item 7 MD&A, etc.). Citations link to the exact passage.
- **Companies House** — UK accounts, filing history, officers, charges. Same chunking discipline.
- **Earnings call transcripts** — last 8 quarters by default. Speaker-turn-aware chunking.
- **Structured news** — Tavily-powered, ranked by recency and source authority.
- **Firm-uploaded content** — playbooks, sector primers, prior reports, frameworks. Tagged at firm scope; retrievable across every engagement at that firm.
- **Proprietary connectors** — PitchBook (private company financials, deal flow), Gong (call recordings and transcripts).

Every source is chunked, embedded, NLI-verified, and trust-scored before it can ground a claim.

---

## Your firm, in the system

Argus is not a generic tool. Each firm shapes it.

**Firm knowledge layer.** Upload your sector primers, valuation playbooks, prior engagement reports, internal frameworks. They get chunked, embedded, and become first-class retrieval sources for every engagement at your firm — never leaking across firm boundaries.

**Per-firm consulting modes.** Define your own engagement types. *"Boutique pricing review"* or *"PE due diligence — bolt-on"* gets a custom Writer schema, custom required reasoning branches, custom source priorities, custom output sections. Or use the built-in modes: market entry, M&A diligence, growth strategy, pricing, competitor analysis, target screen.

**Frameworks, structured.** Pyramid Principle auto-checked on every memo. MECE check on every options matrix. 2x2 builder, Porter's Five Forces template, Value Chain template — all render as structured artifacts the writer populates from verified claims, not as decorative slides.

**Branding.** Your logo, colors, and typography in every PDF, deck, and 1-pager. The output looks like your firm because it is your firm.

---

## Human-in-the-loop

No firm ships unedited LLM output to a client. Argus assumes that.

**Claim-level state.** Every claim in MemoEditor is a first-class object with state: accepted, edited, rejected, or overridden. Overrides require a written reason. Every state change is in the audit log.

**Suggested edits.** Mark a sentence "make this sharper" — Argus produces 2–3 alternatives drawn from the same evidence base. The selected alternative inherits the citations.

**Collaboration.** Threaded comments anchored to **section / claim_id / artifact / text_range / artifact_element** (claim-anchored threads survive memo edits because they're attached to ids, not lines). `@`-mentions via email-prefix slugs. Per-engagement comment overview with orphan detection (a claim retired by section-deepening flags every attached thread). Per-section ownership with work-status (`not_started | in_progress | needs_review | done`) and a coverage map with a `ready_to_submit` advisory flag. Derived task aggregation (open changes-requested pointers + unresolved threads + own-section work) plus explicit tasks; a my-work view rolls every engagement an owner touches into one queue. Notifications fan out across nine types (mentions, replies, engagement / section / task assignments, section-needs-review, review-requested, changes-requested, review-approved, version-restored) with a dispatcher that resolves recipients per type, enforces actor-exclusion ("never notify the actor for their own action"), and collapses multi-type events on the same source via `dedup_key`. In-app feed + capture/SMTP email adapter + per-user preferences. *— Phase 4 / Weeks 16-18.*

**Manager review workflow.** Engagements move through `draft → in_review → changes_requested → approved → delivered`. Role-gated transitions (reviewer-or-admin to approve; an `allow_self_approval` firm flag for segregation-of-duties). Structured feedback with section pointers (`blocking | suggestion | nit`) + claim-id deltas; pointer resolution loop. Lock-on-approval: post-approval edits auto-revert state with audit + a `REVIEW_REVERT` version row. Only an approved engagement can export with the "client-ready" watermark. *— Phase 4 / Week 15.*

**Version history with diff + restore.** Every payload-changing action (initial generation, section deepening, manual edit, review-revert, restore) appends a row to `payload_versions` (monotonic per engagement, never overwritten). Diff any two versions — per-section change classification (`added | removed | modified`) plus word-level segments via stdlib `difflib`, claim-id deltas across the standard claim-carrying surfaces. Restore any version — approval-aware (restoring under an approved state auto-reverts to draft with the explicit-confirm gate), in-flight deepening rejected, downstream artifacts flagged stale, lead notified. The full provenance of how a deliverable evolved is one query. *— Phase 4 / Week 19.*

**Post-engagement feedback.** A 60-second form on every shipped memo: *what was wrong with this?* The responses feed our internal eval dataset, which scores model regressions nightly.

---

## How it works

Argus is a multi-agent pipeline behind a structured-output contract. Plain-English flow:

1. **Brief parser.** Turns "M&A target screen for a payments business" into a structured plan: which sections, which questions, which sources to prioritize.
2. **Researchers.** Per-section, in parallel. Each declares which sources it needs (`["sec_filing", "transcripts"]`, etc.) and emits structured claims with grounding.
3. **Analyst.** Synthesizes claims into reasoning chains. Schema-enforced — cannot output an ungrounded claim.
4. **Verifier ensemble.** LLM judge + DeBERTa NLI + numeric/entity overlap. Each claim gets a verdict: `supported_high`, `supported_low`, `weak`, `contradicted`. Verdicts are sticky downward.
5. **Critic.** Reads the assembled draft for MECE violations, internal consistency, Pyramid adherence. Triggers section reruns where needed.
6. **Writer.** Per-mode, per-firm-customized. Reads only verified claims. Writes the memo prose. Citation IDs preserved through to the rendered output.
7. **Renderer.** One verified claim base produces six different artifacts (memo, 1-pager, deck, Excel, email, interview guide). Each artifact independently re-checks every claim against the source registry before rendering — defense in depth.

Cross-family rule: the model that writes a claim is never the model that verifies it. Enforced at startup.

---

## Quality bar

We don't ship vibes.

**Eval harness.** 25+ canonical strategic questions across all consulting modes, each with a gold-standard memo authored by a senior consultant. Scored nightly in CI on factual accuracy, evidence diversity, recommendation specificity, structural adherence, NLI pass rate, contradiction handling. Regressions block deploys.

**Trace observability.** Every agent call, every retrieval, every verifier signal — traced in Langfuse. A failed engagement is debuggable in two minutes.

**Cost discipline.** Per-job cost ceiling, hard-enforced. Per-firm cost analytics dashboard. Typical engagement runs $0.50–$1.00 in API spend.

**Reproducibility.** Same brief, same firm content, same source corpus produces semantically equivalent output across runs. Run-to-run variance on key recommendations is tracked as a quality metric.

---

## Security and enterprise

- **SSO** via Google Workspace and Microsoft Entra
- **SOC 2 Type I audited.** Type II audit in progress.
- **Per-firm data isolation.** Firms cannot retrieve each other's content. Engagement-scoped access controls.
- **Audit log on every state-changing action.** 7-year retention.
- **Encryption at rest** (AES-256) and in transit (TLS 1.3).
- **Key rotation** automated, dependency audit weekly, intrusion logs centralized.
- **Data residency.** EU-resident infrastructure available for UK/EU firms.

---

## For engineers

**Stack.** Python 3.12, FastAPI, Celery, PostgreSQL with pgvector and FTS, Redis, Next.js 14 with TipTap. Multi-LLM via litellm: Anthropic, OpenAI, Google. DeBERTa-v3 cross-encoder runs locally on CPU in a dedicated worker.

**Architecture.** Multi-tenant from day one. Each engagement is an isolated session; chunks, claims, and verdicts scope to (firm, engagement) tuples. Researcher agents run in parallel per section. Cross-family verifier enforced at boot. Hybrid retrieval (dense + sparse + RRF + optional Cohere rerank).

**Schema-enforced contracts.** Every agent communicates via Pydantic models. The analyst's output cannot serialize without source grounding on every claim. The writer cannot serialize without preserving every citation. Schemas catch class of bugs that prose-based agent communication never can.

**Repo.**

```
backend/
  agents/         # planner, researcher, analyst, critic, verifier, writer
  core/
    nli/          # DeBERTa client, lexical overlap, aggregator
    retrievers/
      edgar/      # SEC EDGAR fetch + parse + chunk + ingest
      companies_house/
      transcripts/
      news/       # Tavily-backed
    feature_flags.py
    provider_family.py    # cross-family verification enforcement
  config/
    consulting_modes.yaml # built-in modes; per-firm overrides layered on top
    models.yaml           # multi-provider routing
  workers/
    nli_worker.py         # dedicated DeBERTa Celery worker
  tasks/                  # Celery pipeline
  db/migrations/
frontend/
  components/
    MemoEditor/           # claim-level state, suggested edits, comments
    ReviewWorkflow/       # draft → review → approved
    DeliverableExports/   # memo, 1-pager, deck, Excel, email, interview guide
docs/
  eval/                   # weekly regression decisions, gold-standard memos
```

**Dev setup.**

```bash
git clone https://github.com/argus-consulting/argus
cd argus
cp .env.example .env       # fill in OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY
docker compose up --build  # api, worker, nli_worker, postgres, redis
cd frontend && npm install && npm run dev
open http://localhost:3000
```

The seeded demo workspace runs with no API keys — useful for evaluation. Real engagements need keys.

---

## Pilot

We work with a small number of boutique consulting firms at a time. Pilot terms:

- 90-day pilot at no cost
- Firm runs at least 3 real engagements through Argus during the pilot
- Weekly working session with one of your senior consultants
- Written testimonial at the end if it lands

Conversion to paid: £1500–3500 per consultant per month, depending on volume and connector requirements.

Contact: hello@argus-consulting.io

---

## Status

**Current version:** v0.4 (Phase 4 complete, tag `phase-4-complete`, 2026-05-24). Not v1.0 — v1.0 is when Phase 5 pilots validate the system with real firms on real engagements with real deliverables shipped to real partners. We are not there yet.

**Pilot posture for the verifier (decided 2026-05-27, W22/D5):** **AI-assisted verification with human review required on flagged claims.** Not "fully verified." Week 22's measurement chain (real-claim calibration → diagnosis → targeted fix → re-calibration) brought the verifier's FP-rate-on-supported from a 60% synthetic worst-case down to 43.75% on the same set, with recall-on-insufficient preserved at 93.33% and the red-team catch rate at 94.1%. That's a measurable improvement — but 43.75% is above the 10% bar for a "fully verified" claim. The cross-family verification + verified-claim wedge remains differentiated; the honest framing is that Argus surfaces a claim-level trust signal that the consultant + partner review on flagged items, not that every supported claim is final. The Week 22 wrap-up is at [docs/eval/week22_verifier_quality.md](docs/eval/week22_verifier_quality.md); the live FP / catch-rate / red-team numbers run on the W20 observability dashboard so quality stays monitored through the pilot.

**Phase 1 (closed earlier):** verification spine — SEC EDGAR + Companies House + earnings transcripts + news + uploaded firm content; cross-family verification (different model writes the memo than verifies the claims) with a three-signal NLI ensemble; claim-level source binding so every assertion has a traceable evidence chunk; eval harness with regression-blocking thresholds; Langfuse traces + cost analytics; SSO + per-firm isolation.

**Phase 2 (closed 2026-05-12, tag `phase-2-complete`):** firm knowledge layer with firm-scoped retrieval; layered consulting modes (built-in ← firm ← engagement); M&A diligence as the first built-in mode with deal-shaped schema (synergy estimate, integration plan, valuation framing); structured frameworks library — 2×2, Pyramid, MECE, Porter's Five Forces, Value Chain — populated from verified claims and auto-checked post-write; section deepening agent: point at a section, supply a directive, mode-aware re-retrieval + rewrite + schema validation + diff/accept under a $0.75 per-run cap, full audit trail. Wedge demonstrated end-to-end on a live M&A engagement. See [docs/eval/phase2_close.md](docs/eval/phase2_close.md).

**Phase 3 (closed 2026-05-20, tag `phase-3-complete`):** the full six-artifact deliverable suite. Export-pipeline foundation (`export_artifacts` table, exporter registry, generate-artifact service, four `/api/sessions/{id}/exports` endpoints, on-disk file storage) carrying five concrete artifact families on top of the existing memo: 1-pager (HTML + PDF, Week 10) + consulting deck (PPTX, Week 11) + Excel financial model (XLSX, Week 12) + cover email (MD + HTML + PDF, Week 13) + expert-validation interview guide (MD + HTML + PDF, Week 13). Mode-aware structure (M&A vs growth_strategy produce structurally distinct artifacts), firm-branded via CSS variables (web), per-shape primary colour + logo cache (PPTX), row-1 firm header band + tab colours (XLSX), running header + page-break-driven section transitions (interview guide PDF), inline-styled HTML with no embedded images (email — mail-client-safe). Single-page-equivalent discipline (1-pager) + 12-slide cap with truncate-and-retry (deck) + cross-sheet cell-registry with citation comments on every payload-derived cell (Excel model) + 250-word body cap + attachment-bundle awareness with stale flagging (email) + 15-question cap with priority badges and time chips (interview guide). Week 14 closed with the W8 Run B writer-truncation carry-forward fixed (growth_strategy writer ships on gpt-4o + max_tokens=16000), library ingestion hardened + expanded (6 new fixtures via a sentence-aware chunker + bulk CLI), and the sample workspace "Meridian Advisory" seeded with 3 users, expanded library, and 2 cached engagements producing the full six-artifact bundle. Full six-artifact regression across modes passes 8/8 headline assertions; cross-artifact verdict consistency holds. See [docs/eval/phase3_close.md](docs/eval/phase3_close.md).

**Phase 4 (closed 2026-05-24, tag `phase-4-complete`):** the collaboration layer. Five workstreams interlocking on one shared spine. Week 15 — review / approval workflow (`draft → in_review → changes_requested → approved → delivered`, role-gated transitions, structured feedback with section pointers, lock-on-approval with auto-revert + audit, segregation-of-duties via the firm-level `allow_self_approval` flag). Week 16 — inline threaded comments anchored to section / claim_id / artifact / text_range / artifact_element (claim-anchored threads survive memo edits because the MemoRenderer already exposed `data-claim-id` since Phase 2), `@`-mentions via email-prefix slugs, resolve/unresolve, orphan detection on deepening-retired claims, per-engagement comment overview surface. Week 17 — `engagement_memberships` with four roles (`lead | contributor | reviewer | observer`) + reviewer-alignment with W15 `review_assigned_to`, per-section ownership + work-status + coverage map with `ready_to_submit` advisory, derived task aggregation + explicit tasks + my-work view (every engagement an owner touches rolled into one queue), team panel + section ownership UI + activity feed. Week 18 — notification dispatcher with nine types (mentions, replies, engagement/section/task assignments, section-needs-review, review-requested, changes-requested, review-approved) plus the W19-added VERSION_RESTORED type, hard actor-exclusion + `dedup_key` collapse, in-app feed + capture/SMTP email adapter + per-user `notification_preferences`, notification center UI (bell, feed, deep-link nav, preferences page). Week 19 — `payload_versions` (append-only, monotonic, five `change_type` values: initial, section_deepening, manual_edit, review_revert, restore), `diff_versions` (per-section change + word-level segments via stdlib `difflib`, matching the frontend W9 `DiffPanel` shape), `restore_version` (approval-aware: restoring under an approved state auto-reverts to draft with the explicit-confirm gate; in-flight deepening rejected; artifacts flagged stale; lead notified), four endpoints mounted at `/api/sessions/{id}/versions/...`. Full Phase 4 integration demo runs a 15-step narrative across all five workstreams on the Meridian Kestrel engagement with three real users — 18/18 headline assertions pass + a provenance narrative renders ("This memo went through 4 versions over the engagement…"). See [docs/eval/phase4_close.md](docs/eval/phase4_close.md).

**Phase 5 starting (Weeks 20-25):** quality + observability + enterprise hardening + the real-firm pilots that are the v1.0 gate. Quality: NLI threshold tuning on real-firm evidence corpora, eval harness expansion to cover the Phase 4 demo + Phase 3 six-artifact regression on nightly CI, hallucination red-teaming. Observability: structured logging, per-endpoint + per-LLM-call metrics, request tracing extending the existing Langfuse spans, cost dashboards with operator-visible per-firm spend + ceiling alerts, error monitoring. Enterprise: real SSO (Google Workspace + Microsoft Entra — today's README claim made real), audit export, data retention + GDPR-style deletion, rate limiting, multi-instance deploy with cross-node cache invalidation, backup / restore drill. Pilots: onboarding flow (firm partner self-serves to a runnable first engagement in under 15 minutes), real-firm fixtures, feedback instrumentation wired to the 60-second post-engagement form, the Blackmont + EF 90-day pilots. v1.0 ships when one of the pilot firms signs off on a real client deliverable shipped through Argus end-to-end. Detailed scope at [docs/roadmap/phase5_scope.md](docs/roadmap/phase5_scope.md).

**Honest open items at the Phase 4 boundary:** no production observability surface yet (the per-job cost ceiling is enforced but there's no operator dashboard to watch it on); SSO is dev-only — the production claim is aspirational until the Week 23 enterprise work; the W19/D3 version-history React surface is deferred into Phase 5 (the backend list + diff + restore + endpoints all shipped + tested; the inline diff UI is plumbing on top); production SMTP is wired through an adapter contract but a real provider + DKIM/SPF/bounce-handling is pilot-tier setup; notifications are per-event today (digest batching + WebSocket push deferred); the growth_strategy writer fix from Phase 3 is in production but the Porter's framework schema-enforcement work moved into Phase 5 quality (the sample workspace ships a hand-curated payload so the end-state is visible to demos); PDF artifact rendering still requires WeasyPrint's native libs (pango/cairo/gdk-pixbuf) — fine in Docker, the seeder + regression handle Windows dev hosts via a graceful `skipped_no_weasyprint` status, but it's a documented host requirement for pilot deploys; Companies House TIFF/OCR for scanned historical filings remains open from Phase 1. No real-firm pilots have run yet; no real client deliverables have shipped through Argus end-to-end. v0.4, not v1.0.

**Out of scope:** Replacing the consultant. Argus makes consultants 3–5x faster on research-and-deliverable workflows. The judgment, the client relationship, the recommendation — those stay with the human.

---

*Built in Southampton.*
