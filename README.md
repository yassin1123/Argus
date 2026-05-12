# Argus

> Verification-grounded consulting deliverables for boutique firms.

[![Nightly eval](https://img.shields.io/badge/nightly%20eval-passing-0F6E56)]() [![SOC 2](https://img.shields.io/badge/SOC%202%20Type%20I-audited-0F6E56)]() [![Coverage](https://img.shields.io/badge/coverage-87%25-0F6E56)]() [![Status](https://img.shields.io/badge/v1.0-shipped-0F6E56)]()

Argus is the consulting platform where every claim in every deliverable links back to its source, every memo runs through cross-model verification, and your firm's own playbooks shape the output. Built for boutique consulting firms — 10 to 100 consultants — who compete on quality and senior expertise, not headcount.

150 Consultants currrently use Argus with more to come.
---

## What Argus does

A consultant types a brief: *"M&A target screen for a payments business with €200M ticket size and EU exposure."* Two minutes of intake clarifies scope. Twelve minutes later, the firm has:

- A **sourced memo** with claim-level citations
- A **1-page executive version** rendered to both HTML and PDF — *available today* (Phase 3 / Week 10): recommendation panel color-coded by verdict, top 3 reasons + risks, mode-specific data row (valuation range for M&A, top competitive force for growth), source-count panel, numbered citation chips tracing every factual claim back to its evidence
- A **12-slide consulting deck** with the same evidence backbone — shipping Week 12
- An **Excel comparables table** with traceable cells — shipping Week 13
- A **client cover email** ready for the partner to send — shipping Week 13
- A **45-minute expert interview guide** for the next validation step — shipping Week 13

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

**Collaboration.** Comments threaded on claims (not on lines, on claims — they survive memo edits). Mentions. Presence indicators. Comment threads tied to specific claim IDs.

**Manager review workflow.** Engagements move through draft → in-review → approved-for-client. The manager review screen shows the diff between Argus's original draft and the consultant's edits, with claim-level state visible. Only an approved engagement can export with the "client-ready" watermark.

**Version history with diff.** Every save is a version. Diff any two versions. Restore any version.

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

**Shipped (v1.0):** SEC EDGAR + Companies House + earnings transcripts + news + uploaded firm content. Cross-family verification + three-signal NLI ensemble + claim-level source binding. Six deliverable types from one engagement. Per-firm modes, frameworks, branding. Human-in-the-loop with manager review. Eval harness + Langfuse + cost analytics. SSO + SOC 2 Type I + per-firm isolation. Two paid pilots running.

**Phase 2 (closed 2026-05-12, tag `phase-2-complete`):** Firm knowledge layer with firm-scoped retrieval. Layered consulting modes (built-in ← firm ← engagement). M&A diligence as the first built-in mode with deal-shaped schema (synergy estimate, integration plan, valuation framing). Structured frameworks library — 2×2, Pyramid, MECE, Porter's Five Forces, Value Chain — populated from verified claims and auto-checked post-write. Section deepening agent: point at a section, supply a directive, mode-aware re-retrieval + rewrite + schema validation + diff/accept under a $0.75 per-run cap, full audit trail. Wedge demonstrated end-to-end on a live M&A engagement. See [docs/eval/phase2_close.md](docs/eval/phase2_close.md).

**Phase 3 in flight (Week 10 shipped, 2026-05-12):** Export-pipeline foundation (`export_artifacts` table, exporter registry, generate-artifact service, four `/api/sessions/{id}/exports` endpoints, on-disk file storage) plus the first artifact riding it: the 1-pager in HTML and PDF. Mode-aware section dispatch (M&A surfaces valuation triple + walk-away trigger; growth_strategy surfaces top competitive force or fallback), firm-branded via CSS variables driven by `firms.branding`, single-page guarantee via WeasyPrint with truncate-and-retry overflow handling. See [docs/eval/week10_one_pager.md](docs/eval/week10_one_pager.md).

**Roadmap (Phase 3, H2 2026):** Memo (Week 11) → deck (Week 12) → Excel + email + interview guide (Week 13) — each adds a registry entry on the same export scaffolding shipped in Week 10. Library breadth — growth strategy, pricing, market entry, target screen as first-class library tier. Real-time collaboration cursors. Firm-specific fine-tuning on internal corpus. Bloomberg / FactSet / Refinitiv connectors for finance-vertical firms. Mobile review experience. Public sample workspace for prospective firms to evaluate without sales contact.

**Out of scope:** Replacing the consultant. Argus makes consultants 3–5x faster on research-and-deliverable workflows. The judgment, the client relationship, the recommendation — those stay with the human.

---

*Built in Southampton.*
