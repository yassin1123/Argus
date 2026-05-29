# Argus

> Verification-grounded consulting deliverables for boutique firms.

![version](https://img.shields.io/badge/version-1.0.0-0F6E56) ![pilot](https://img.shields.io/badge/pilot-launched-0F6E56) ![verifier](https://img.shields.io/badge/verifier-GREEN%20(conservative)-0F6E56)

Argus is the consulting platform where every claim in every deliverable links back to its source, every memo runs through cross-family verification, and your firm's own playbooks shape the output. Built for boutique consulting firms — 10 to 100 consultants — who compete on quality and senior expertise, not headcount.

**v1.0 status (honest):** Argus is at v1.0 because **a real boutique firm is using it in a live pilot** — not because every imaginable feature is built. It ships with documented bounds: the verification layer is **GREEN-gated but deliberately conservative**, several enterprise features are explicitly deferred to post-1.0, and the pilot is *launched and running* — whether it's *successful* is the retrospective's call, not this README's. See [`docs/v1.0/scope.md`](docs/v1.0/scope.md) for the exact in/out line.

---

## What Argus does

A consultant types a brief: *"M&A target screen for a payments business with €200M ticket size and EU exposure."* Intake clarifies scope. Minutes later, the firm has a verified claim base that renders into six deliverables:

- A **sourced memo** with claim-level citations
- A **1-page executive version** (HTML + PDF)
- A **consulting deck** (PPTX) — mode-aware structure, firm-branded
- An **Excel financial model** (XLSX) with cross-sheet formulas + citation comments on payload-derived cells
- A **client cover email** (MD / HTML / PDF), attachment-aware
- A **45-minute expert interview guide** (MD / HTML / PDF) targeting the analysis's evidence gaps

Every factual claim across all six traces back to a specific source passage, and every claim was checked by a model from a **different provider family** than the one that wrote it. The consultant reviews claim by claim, the senior approves the diff, and only an approved engagement exports with the "client-ready" watermark.

---

## The verification spine — and what it actually guarantees

Argus's wedge is verification. The honest, measured version:

**Cross-family verification, enforced at boot.** The model that writes a claim is never the model that verifies it (Anthropic synthesis × an OpenAI **gpt-4o** judge). Same-family verification is theatre — models share biases and ratify each other's hallucinations. Argus **refuses to start in production** if the configuration can't run the real cross-family verifier (no silent heuristic fallback — ever).

**Three-signal NLI ensemble.** An LLM judge + a DeBERTa-v3 cross-encoder running locally + a numeric/named-entity overlap detector. The aggregator only downgrades — it can move "supported" to "weak" or "contradicted," never up.

**The measured guarantee (W24/D1 real-claim gate).** On **61 human-labelled real engagement claims** scored through the real cross-family verifier:

| Metric | Value |
|---|---|
| False-positives on "supported" | **0%** (0/7) |
| Recall on insufficient (catch rate) | **100%** (4/4) |
| Recall on supported | ~27% |
| Verdict | **GREEN** |

**The posture is "verified (conservative)," not "perfectly verified."** When Argus marks a claim *supported*, it was right every time on the real-claim set. The trade-off is deliberate caution: it **over-flags** — it down-grades many genuinely-supported claims to "needs review" rather than risk a wrong "supported." That means a human reviews flagged claims before a client sees anything. Erring on the safe side is the design choice; reducing the over-flagging without raising the false-positive rate is post-1.0 work.

---

## Sources

Argus retrieves from real, citable sources — no synthetic web summaries.

- **SEC EDGAR** — 10-K, 10-Q, 8-K, DEF 14A, S-1. Item-aware chunking; citations link to the exact passage.
- **Companies House** — UK accounts, filing history, officers, charges. *(Scanned/image-only historical filings need OCR — deferred to post-1.0.)*
- **Earnings call transcripts** — speaker-turn-aware chunking.
- **Structured news** — recency- and authority-ranked.
- **Firm-uploaded content** — playbooks, sector primers, prior reports, frameworks; firm-scoped, retrievable across every engagement at that firm, never crossing firm boundaries.

Every source is chunked, embedded, NLI-verified, and trust-scored before it can ground a claim.

---

## Your firm, in the system

- **Firm knowledge layer.** Upload your sector primers, valuation playbooks, prior reports, frameworks — chunked, embedded, first-class retrieval sources for every engagement at your firm, never leaking across firms.
- **Layered consulting modes.** Built-in modes (general, market entry, due diligence, growth strategy, M&A diligence) with per-firm overrides (built-in ← firm ← engagement).
- **Structured frameworks.** Pyramid + MECE checks; 2×2, Porter's Five Forces, Value Chain rendered from verified claims, not decoration.
- **Branding.** Your logo, colours, footer in every PDF, deck, 1-pager, and email.

---

## Collaboration

- **Manager review workflow.** `draft → in_review → changes_requested → approved → delivered`, role-gated, structured feedback with section pointers, lock-on-approval with auto-revert + audit.
- **Comments** anchored to section / claim_id / artifact / text_range (claim-anchored threads survive memo edits), `@`-mentions, resolve/unresolve, orphan detection.
- **Ownership + tasks.** Per-section ownership + work-status, derived + explicit tasks, a my-work queue across every engagement an owner touches.
- **Notifications.** In-app feed + email adapter, actor-exclusion + dedup.
- **Version history.** Every payload-changing action appends an immutable version; diff any two (per-section + word-level) and restore (approval-aware).

---

## Observability + enterprise

**Observability (in-house, W20).** Structured logs with trace IDs, per-endpoint + per-LLM-call metrics, a cost ledger, request-lifecycle trace assembly, an admin dashboard, and a **live-pilot watch view** with operator alerting (engagement failure / error-rate spike / budget threshold / anomalous verification distribution).

**The four enterprise pillars (W23).**
- **Tenant isolation** — centralized guard; cross-firm access returns 404 (anti-enumeration).
- **Data retention + hard deletion** — per-firm window + grace; purge across 20 tables; content-free purge audit.
- **Audit export** — append-only audit log; firm-scoped, content-free CSV/NDJSON.
- **Cost governance** — per-firm monthly budget (soft-stop at 100%), per-session ceiling, rate limits, operator cost-burn alerts.

**Encryption + secrets (deploy-level, W24).** TLS in transit (automatic via the deploy's reverse proxy); encryption-at-rest is a **deploy requirement** (managed Postgres + encrypted artifact volume) — application-level field encryption is post-1.0. Secrets come from the environment / a managed secret store, never committed, never logged.

---

## In v1.0 vs coming

**In v1.0** (built, verified, in the pilot): the verification spine; the six-artifact suite; firm knowledge + layered modes; the full collaboration layer; observability; the four enterprise pillars; the GREEN-gated "verified (conservative)" verifier; production deploy config + operator runbook.

**Explicitly post-1.0** (named, not hidden): SSO / SAML; application-level field encryption; external pen-test / SOC 2; Companies House OCR; multi-instance / HA; notification digests + real-time push; element-level artifact commenting; text-range re-anchoring; verifier-recall improvement (the conservative-trait work); and whatever the pilot's live edit-rate signal points at.

Full detail: [`docs/v1.0/scope.md`](docs/v1.0/scope.md). Release notes: [`CHANGELOG.md`](CHANGELOG.md).

---

## For engineers

**Stack.** Python 3.12, FastAPI, Celery, PostgreSQL (pgvector + FTS), Redis, Next.js 14. Multi-LLM via litellm (Anthropic, OpenAI, Google). DeBERTa-v3 cross-encoder runs locally on CPU in a dedicated worker.

**Architecture.** Multi-tenant from the schema up — chunks, claims, and verdicts scope to (firm, engagement). Researcher agents run in parallel per section. Cross-family verification enforced at boot. Hybrid retrieval (dense + sparse + RRF + optional rerank). Every agent communicates via Pydantic models — the analyst's output can't serialize without source grounding on every claim.

**Pipeline.** planner → researchers (parallel) → analyst → verifier ensemble → critic → writer → renderer. One verified claim base → six artifacts, each re-checking every claim against the source registry before rendering.

**Dev setup.**

```bash
cp .env.example .env        # fill in OPENAI_API_KEY, ANTHROPIC_API_KEY (both required)
docker compose up --build   # api, worker, nli_worker, postgres, redis, minio
cd frontend && npm install && npm run dev
open http://localhost:3000
```

The seeded demo workspace runs in `DEMO_MODE` without API keys — useful for evaluation. Real engagements need both LLM keys (the cross-family verifier).

**Production deploy.** Target-agnostic config in [`deploy/`](deploy/) (managed Postgres with encryption-at-rest, automatic TLS, secrets via env/secret-store, fail-loud production boot guard, idempotent migration runner) + a repeatable procedure in [`deploy/README.md`](deploy/README.md). Operator runbook: [`docs/pilot/runbook.md`](docs/pilot/runbook.md).

---

## Pilot status

Launched and running with one boutique firm. **"Launched and running" is not "successful"** — success is measured by the live signals (edit rate, claim-feedback agreement, artifact ratings) and is the retrospective's call. The pilot's learning lives in [`docs/pilot/learnings.md`](docs/pilot/learnings.md).

**Out of scope (by design):** replacing the consultant. Argus accelerates research-and-deliverable work; the judgment, the client relationship, and the recommendation stay with the human.

---

*Built in Southampton.*
