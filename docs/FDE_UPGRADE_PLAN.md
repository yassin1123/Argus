# Plan — Make Argus Look Like a Real, Credible Client AI System

## Reality Check First

A recruiter scanning the repo for 30 seconds wants to know:
1. Can I understand it fast?
2. Does it look real?
3. Is there **proof** it works?
4. Does it map to the role?
5. Will the code hold up if an engineer checks it?

This plan splits work into:
- **Surface** — make existing features visible (README, screenshots, video)
- **Polish** — tighten built-but-rough UX (trust rail, SSE, branding)
- **Build** — genuinely missing (evidence graph, case study deliverable, CI)
- **Proof** — engineering credibility (tests, CI, fixtures, deterministic demo)

A lot of the listed features **already exist** in the code; the work is largely about making them legible and adding the proof layer.

---

## Phase 1 — README Rewrite (Highest ROI, do first)

**Replace [README.md](../README.md) with a hero-style README.**

### Tone

- **Don't spam "FDE."** Once in a "Why this matters for deployment" section is enough — overusing it makes the repo look built-to-impress, not built-to-work.
- Lead with the product, not the buzzword.

### Hero

```
# Argus — Evidence-Grounded AI Decision Engine

A full-stack AI system for turning messy strategic questions, uploaded documents,
and web evidence into verified client-ready reports with citations, confidence,
caveats, and exportable deliverables.
```

### Structure

1. **Hero** — title, tagline, badge row (Python 3.11, FastAPI, Next.js, Postgres+pgvector, Celery, Docker, CI passing)
2. **Demo block** — Loom/YouTube link, live demo URL placeholder, 1 hero screenshot/GIF
3. **The problem** — 3 sentences. Generic chatbots hallucinate; consultants are slow. Argus produces verified, citation-backed strategic reports.
4. **Example use case** — *"Should a SaaS company enter Germany or France first?"* → links to the full case study folder (Phase 4)
5. **Architecture diagram** — Mermaid (renders natively on GitHub)
6. **Feature grid** — 9 features × 1-line description × thumbnail screenshot
7. **Quickstart** — `make demo` then open `localhost:3000`. That's it.
8. **The pipeline** — agent-by-agent breakdown with one-line responsibilities
9. **Engineering quality** section (see Phase 9 — non-negotiable)
10. **Why this matters for deployment** — *one* paragraph mentioning forward-deployed AI principles (ambiguous client problem, messy evidence, auditable reasoning, polished deliverable). This is where "FDE" framing lives, contained.
11. **Tech stack** table
12. **CV bullet** in a `<details>` block at the bottom

Files to create:
- `docs/screenshots/` — 6–8 PNGs (Phase 5)
- `docs/architecture.md` — deep diagrams
- `docs/case-studies/germany-vs-france/` — full deliverable (Phase 4)

---

## Phase 2 — One-Command Run + Demo Mode

Goal: clone → run **one command** → see the app at `localhost:3000` populated with a finished example. **No API key required.**

This is the single biggest "this is real" signal in the whole plan.

**Changes:**
1. Add `DEMO_MODE=1` toggle in `.env.example` that lets the app boot without `OPENAI_API_KEY` and serves the **pre-canned Germany vs. France report** plus 2 other seeded engagements.
2. Add `Makefile` with:
   ```
   make demo   # docker compose up + auto-seed + opens browser
   make seed   # loads example sessions + canned reports
   make stop
   make test   # runs backend test suite
   ```
3. Add `scripts/seed_demo.py` — inserts finished sessions into Postgres so the homepage and workspace are populated immediately.
4. Add `docker-compose.demo.yml` override that auto-seeds on boot.
5. Demo mode bypasses LLM calls and returns deterministic fixtures from `backend/tests/fixtures/` (also reused by tests — see Phase 9).

---

## Phase 3 — Evidence Graph Visualization (the differentiator)

**Current state:** Evidence stored as rows in `evidence_objects`; displayed as a list in `frontend/components/sessions/EvidenceRail.tsx`. The `reasoning_graph` JSONB field exists in `reports` but isn't visualized.

**Risk:** A pretty random node graph is gimmicky. To avoid that, the graph must be *useful* — every node clickable, every edge meaningful.

**Build plan:**
1. **Backend** — extend `backend/models/reasoning.py` to emit a normalized graph:
   ```
   nodes: [{id, type: claim|evidence|source, label, confidence, verifier_verdict?}]
   edges: [{from, to, kind: cites|contradicts|supports}]
   ```
2. **API** — `GET /api/workspaces/{id}/graph` returns the normalized graph.
3. **Tests** — `backend/tests/test_graph_normalize.py` covers the normalization. (See Phase 9.)
4. **Frontend** — new component `frontend/components/Report/EvidenceGraph.tsx` using **react-flow** (lighter than cytoscape).
   - Click a claim node → highlights its supporting evidence + verdict in a side panel
   - Click an evidence node → opens the source quote
5. **Tabs on workspace page** — `Answer | Graph | Audit | Sources`. Graph is the new tab.
6. **Styling** — color nodes by `verifier_verdict` (green=supported, amber=weak, red=unsupported, gray=inference). This is the screenshot money shot.

**Mandatory:** the graph must show real claim → evidence → source → verifier verdict relationships. If it can't do that, don't ship it as a graph; keep it as a list.

---

## Phase 4 — The Case Study Deliverable (treat as primary artifact)

This is the missing centerpiece — what makes the repo feel like a real engagement, not a tech demo.

**Folder structure:**
```
docs/case-studies/germany-vs-france/
├── README.md              # narrative wrapper
├── prompt.md              # exact strategic question asked
├── input-notes.md         # uploaded docs summary, context provided
├── final-report.pdf       # exported consulting deliverable
├── final-report.md        # markdown version for GitHub viewing
├── evidence-graph.png     # screenshot of the graph view
├── verifier-report.md     # claim-by-claim verdicts
└── screenshots/           # workspace, trust rail, audit panel
```

**Each case study answers:**
- What was the question?
- What evidence was used?
- What did the system produce?
- How did the verifier check it?
- What would be delivered to a client?

**Plan:** ship one full case study (Germany vs. France). Stub two more (`m-and-a-targetco/`, `growth-strategy-pricing/`) so the directory feels like a portfolio of engagements. Stubs each contain at minimum: `README.md` + `prompt.md` + 1 screenshot.

**Why this matters:** before → process → output is the strongest portfolio pattern. The case study turns Argus from "code that runs" into "system that delivers."

---

## Phase 5 — Screenshots + Demo Video

**Screenshots to capture** (target 6–8):
1. **Composer / new session** — "Should we enter Germany or France?"
2. **Intake Q&A** — clarifying questions stage
3. **Live processing** — SSE streaming, agents lighting up sequentially
4. **Workspace finished** — three-column with answer + evidence + trust rail
5. **Evidence graph** — Phase 3 viz
6. **Trust rail close-up** — confidence, caveats, unsupported-claims badge
7. **Audit panel** — agent timeline (planner → researcher → analyst → critic → verifier → writer)
8. **Exported PDF** — first page of the rendered consulting memo

Save to `docs/screenshots/`. Reuse in `docs/case-studies/germany-vs-france/screenshots/`.

**Demo video** (3 minutes, Loom):
- 0:00–0:20 — the problem (chatbots hallucinate, consultants are slow)
- 0:20–0:40 — paste a real strategic question
- 0:40–1:00 — upload a PDF (e.g., a market report)
- 1:00–2:00 — pipeline running live with SSE; narrate each agent
- 2:00–2:40 — finished report; click through evidence graph; show trust rail
- 2:40–3:00 — export PDF; show consulting-grade output

---

## Phase 6 — Client Workspace Branding (Honest Demo Framing)

**Current state:** UI says "Argus" but doesn't *feel* like a client product.

**Critical:** make it obvious this is a **demo**, not a real client engagement. Pretending otherwise looks dishonest.

**Polish pass:**
1. **Client header** on workspace page — but framed honestly:
   - ✅ `"Demo engagement · Prepared for ExampleCo · Confidential"`
   - ✅ `"Sample client workspace · Germany vs France market entry"`
   - ❌ `"Prepared for Acme Corp · Confidential · April 2026"` (looks fake/dishonest)
2. Add `client_name` + `engagement_type` fields via migration `011_client_metadata.sql`. Seed values clearly say "Demo" / "Example".
3. Deliverable feel for the answer canvas: page-like white card, serif headline for the recommendation, footer line *"Generated by Argus · Evidence-grounded · Demo workspace"*.
4. Three demo engagements visible on the home page sidebar (matches Phase 4 case studies):
   - "Demo · SaaS market entry — Germany vs France"
   - "Demo · M&A diligence — ExampleCo financials"
   - "Demo · Growth strategy — pricing model shift"
5. Update `frontend/components/home/HomeHeader.tsx` tagline.

---

## Phase 7 — SSE Polish

**Current state:** SSE endpoint exists; ProcessingCenter renders progress.

**Polish:**
1. **Timestamps + per-step duration** (already in `pipeline_events.at`).
2. **Live token / cost counter** — pulls from `agent_outputs.token_count`. Big "production" signal.
3. **Narration line** — *"Researcher is reviewing 12 sources across 4 search queries"* — built from event payload.

---

## Phase 8 — Verifier / Confidence Surfacing

**Current state:** `verifier.py` runs, `claim_support_rows` persisted, TrustRail renders confidence.

This is arguably **more important than the graph** for the enterprise-AI signal — auditability, confidence, caveats, safe delivery.

**Polish:**
1. **Inline citation chips** next to each claim → side drawer with the evidence object (Perplexity-style).
2. **"Verifier Report" expandable section** — every claim with verdict (supported / weak / unsupported / overstates). Already computed; surface it.
3. **Caveat banner** at the top of any report with `unsupported_claim_count > 0`: *"This report contains N unsupported claims. Review before client delivery."*

---

## Phase 9 — Engineering Quality Proof (NEW — non-negotiable)

Recruiters who scan look at presentation. Engineers who actually open the repo look at this. Without it, the code looks like vibes.

### Must-have engineering signals

1. **Backend tests** — `backend/tests/`
   - `test_graph_normalize.py` — evidence graph schema (Phase 3)
   - `test_claim_support_rows.py` — verifier claim row construction
   - `test_evidence_gates.py` — strict mode, inference-only ban
   - `test_demo_seed.py` — seeded session loads end-to-end
2. **API response fixtures** — `backend/tests/fixtures/germany_vs_france/`
   - `planner_output.json`, `research_payload.json`, `analyst_output.json`, `verifier_output.json`, `writer_payload.json`
   - Reused by `DEMO_MODE=1` and the test suite — single source of truth.
3. **GitHub Actions CI** — `.github/workflows/ci.yml`
   - Backend lint + type check + pytest
   - Frontend `tsc` + `next build`
   - Docker Compose smoke test (`make demo` + curl `/api/health`)
4. **Smoke test** — `tools/smoke_check.sh` (already exists) hooked into CI.
5. **Status badges** in README hero — CI passing, Docker build, tests count.

### README "Engineering quality" section

```
## Engineering quality

- Deterministic demo mode with seeded workspace (no API key required)
- Normalized evidence graph schema with unit tests
- Verifier outputs persisted per claim; surfaced in UI with verdicts
- Dockerized local environment, one command to run
- CI checks for backend tests, type checks, frontend build, demo smoke test
- Full sample case study included (prompt → evidence → report → verification)
```

---

## Phase 10 — CV Bullet + Recruiter Hooks

In README:
```
Built Argus — a full-stack AI decision engine using FastAPI, Celery, Redis,
PostgreSQL/pgvector and Next.js — converting uploaded documents and strategic
questions into evidence-backed reports with verifier agents, confidence scoring,
and exportable client deliverables (PDF, PPTX, memo).
```

Plus `docs/case-study.md` — a 1-page meta write-up: how Argus's architecture maps to a real client deployment (multi-tenant, auth, audit log, etc.). Frame it as *"What I'd add on day one of a client engagement."*

---

## Suggested Build Order

| Phase | Effort | Visible Impact | Order |
|-------|--------|---------------|-------|
| 1. README rewrite (no FDE spam) | 2h | Massive | **First** |
| 2. One-command demo mode | 4h | Massive | Second |
| 4. Germany-vs-France case study | 4h | Massive | Third |
| 5. Screenshots + video | 4h | Massive | Fourth (needs 1+2+4) |
| 9. Engineering quality (tests + CI) | 6h | High (credibility) | Fifth |
| 3. Evidence graph | 6h | High (money shot) | Sixth |
| 8. Verifier surfacing | 3h | High (enterprise signal) | Seventh |
| 6. Honest demo branding | 2h | Medium | Eighth |
| 7. SSE polish | 2h | Medium | Ninth |
| 10. CV bullet / case study meta | 1h | Low (but quick) | Last |

**Total:** ~34h. **Phases 1+2+4+5 (~14h)** make the repo feel real to a recruiter. **Phase 9 (~6h)** makes it feel real to an engineer. **Phase 3 + 8 (~9h)** is the differentiation work. Everything else is polish.

**Minimum viable shippable subset:** 1 + 2 + 4 + 5 + 9 = ~20h. Skip the graph if time-pressured; it's the differentiator, not the foundation.

---

## What I'm NOT Recommending

- **Auth / multi-tenancy** — overkill for a portfolio repo; mention in case study instead.
- **Rewriting agents** — pipeline is already strong; don't break what works.
- **New LLM providers** — OpenAI alone is fine for the demo.
- **Real-time collaboration** — out of scope; would dilute focus.
- **Fake client names** — looks dishonest. Always frame as "Demo" / "Example".
- **Spamming "FDE"** — once is enough; product first, framing second.

---

## Original Feature Brief (for reference)

| Feature | Why it matters |
|---------|----------------|
| Client workspace | Shows customer-facing product thinking |
| Document upload + retrieval | Shows real enterprise AI/RAG skill |
| Evidence graph | Makes it more serious than a chatbot |
| Verifier agent | Shows reliability/evaluation thinking |
| Confidence/caveat panel | Looks consulting-grade and enterprise-safe |
| PDF / memo / deck export | Very FDE/client-delivery coded |
| SSE progress updates | Shows production UX |
| Docker one-command run | Makes it recruiter-friendly |
| Screenshots + demo video | Makes it instantly understandable |

### Target README hero

```
# Argus — Evidence-Grounded AI Decision Engine

A full-stack AI system for turning messy strategic questions, uploaded documents,
and web evidence into verified client-ready reports with citations, confidence,
caveats, and exportable deliverables.
```

### Target Demo block

```
## Demo
- Live demo: <link>
- 3-minute walkthrough: <YouTube/Loom link>
- Example use case: "Should a SaaS company enter Germany or France first?"
- Full case study: docs/case-studies/germany-vs-france/
```

### Target Architecture block

```
## Architecture
Frontend: Next.js + Tailwind
Backend: FastAPI
Worker: Celery + Redis
Database: PostgreSQL + pgvector
AI Pipeline: Planner → Researcher → Analyst → Critic → Verifier → Writer
Exports: PDF, memo, report, PPTX
```

### Target "Why this matters for deployment" block (where FDE framing is contained)

```
## Why this matters for deployment

Argus is built around the realities of forward-deployed AI work: ambiguous
client problems, messy evidence, the need for auditable reasoning, fast
iteration, and a polished deliverable a client can actually take to a meeting.
```
