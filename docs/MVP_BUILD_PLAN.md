# Argus MVP — Build Plan (10 Phases)

This is the engineering plan to ship the **MVP** as scoped in [`docs/day-one.md`](day-one.md) and the engineering brief: a workbench one design partner can use end-to-end on a real engagement, with provenance you can defend in a partner-review meeting.

**MVP scope (per the brief):**
- Single tenant
- Email/password auth (no SSO yet)
- Source library: PDF upload + URL fetch + manual classification
- Single model (**OpenAI** for this build — not Claude — using the API key already in `.env`) with structured citations
- 3-pane workbench UI (already shipped)
- Conversation with inline citations + hover popovers (already shipped)
- Memo artifact with DOCX export
- Basic engagement-level permissions
- Postgres + pgvector + S3 (local MinIO) — OpenSearch deferred to v1

**What's already done (don't rebuild):**
- 3-pane workbench shell + Source Rail / Conversation / Artifacts Rail
- Inline citation markers with hover popovers
- Trust-tier color coding (firm / credible / web / contested)
- "Show the work" toggle (cosmetic in MVP since one model — wired for v1 multi-model)
- pgvector embeddings + retrieval skeleton
- Pipeline (planner → researcher → analyst → critic → verifier → writer)
- `evidence_objects` + `claim_support_rows` schema (will be evolved into `chunks` in Phase 4)
- Demo seed + fixtures + Docker Compose

**What MVP adds (10 phases below).** Each phase ships, gets tested, gets committed before the next starts. Same cadence as the UI redesign.

---

## Phase 1 — Auth (email/password)

**Goal:** every API call is authenticated. Users can register, log in, log out. Sessions persist across reloads.

**Backend:**
- Migration `012_users_and_sessions.sql` — tables `users` (id, email, password_hash, full_name, role, created_at) and `sessions_auth` (id, user_id, token_hash, expires_at, ip, user_agent).
- bcrypt password hashing (`passlib[bcrypt]`).
- New module `backend/auth/` — `register`, `login`, `logout`, `current_user` dependency.
- New API routes: `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`.
- FastAPI dependency `get_current_user` mounted on every existing route via a shared dependency. Anonymous calls → 401.
- Rate-limit register/login (slowapi already in repo).

**Frontend:**
- `app/(auth)/login/page.tsx` and `app/(auth)/register/page.tsx` — minimal forms in the new design system.
- Cookie-based session (HTTP-only, SameSite=Lax). Server reads session on every request.
- Middleware `middleware.ts` redirects unauthenticated users to `/login` for any non-auth route.
- Account drop-down in the left rail bottom (replaces the `YA` placeholder).

**Deliverable test:** create a fresh user, log in, hit `/` and see only that user's engagements. Open another browser, log in as a second user, see no overlap.

---

## Phase 2 — Engagement memberships + permissions

**Goal:** an engagement is owned by a user, can be shared with teammates with roles. Non-members can't read it.

**Backend:**
- Migration `013_engagement_memberships.sql` — table `engagement_memberships` (engagement_id, user_id, role: `lead | member | viewer`, added_by, added_at, UNIQUE(engagement_id, user_id)). Add `created_by_user_id` to `sessions`.
- Permission helper `backend/auth/permissions.py` — `can_read_engagement(user, engagement_id)`, `can_write_engagement`, `can_admin_engagement`.
- Every existing engagement route (sessions, workspace, chat, exports, intake) gets a permission check before responding.
- `POST /api/engagements/{id}/members` (lead only), `DELETE /api/engagements/{id}/members/{user_id}`.
- `GET /api/sessions` filters to engagements the user is a member of.

**Frontend:**
- New "Team" panel in the workspace top-bar overflow menu (avatar stack + add-member dialog).
- Engagements home shows only engagements the current user has access to.
- Read-only mode for `viewer` role: composer disabled, exports allowed, no run/edit.

**Deliverable test:** user A creates an engagement, invites user B as `member`. B sees it on their home and can run it. User C (not invited) gets 404.

---

## Phase 3 — S3 / MinIO blob storage

**Goal:** source files live in object storage, not in Postgres. Foundation for ingest scale + cheap re-embedding later.

**Backend:**
- Add `minio` service to `docker-compose.yml` — S3-compatible local store on port 9000.
- New module `backend/storage/blob.py` — `upload_blob`, `get_signed_url`, `delete_blob` using `boto3` against the MinIO endpoint. Same code works against AWS S3 in production by changing env vars.
- Migration `014_source_blobs.sql` — table `source_blobs` (id, session_id, key, size, content_type, sha256, uploaded_at). Replace `uploaded_files.content` with a foreign key to `source_blobs`.
- Background migration script: copy existing `uploaded_files.content` blobs into MinIO, drop the column.
- File-upload endpoint streams to MinIO instead of holding the bytes in memory.

**Frontend:**
- No visible change yet — same upload UI, faster on big files.

**Deliverable test:** upload a 50MB PDF without OOMing the backend. Confirm the row in `source_blobs` and the object in MinIO. Re-download via signed URL.

---

## Phase 4 — Chunk-level data model + section-aware chunking

**Goal:** every citation references a chunk with real metadata (page, slide, section, timestamp), not a coarse `evidence_object`. This is the spine of the citation magic — non-negotiable per the brief.

**Backend:**
- Migration `015_chunks.sql` — table `chunks` (id UUID, source_id, session_id, content TEXT, embedding vector(1536), source_type, position, page INT, slide INT, timestamp TEXT, section_heading TEXT, hash, created_at). Indexed on (session_id, source_type, page).
- `evidence_objects` becomes a *view* over `chunks` for backward compat during the transition; drop the table at the end of the phase.
- New chunker module `backend/ingest/chunking/` with three strategies:
  - `pdf_section_chunker.py` — uses PyMuPDF section detection, one chunk per section if available, else one per page.
  - `transcript_chunker.py` — speaker-turn chunking with timestamps. Recognizes `Speaker:` and `[00:12:34]` patterns.
  - `web_chunker.py` — semantic chunking (BeautifulSoup → headings → paragraphs).
- `backend/ingest/pipeline.py` — runs synchronously inside the upload endpoint for MVP (Celery in v1).
- Migration of seeded fixtures: convert Germany-vs-France `evidence.json` rows into the new `chunks` shape.

**Frontend:**
- Citation popover surfaces page / slide / timestamp from chunk metadata when present.
- Source rail row shows page count or section count under the title.

**Deliverable test:** upload a 30-page PDF. Confirm 30+ chunks created with correct page numbers. Click a citation → popover shows the page number.

---

## Phase 5 — Source library UI + manual trust classification

**Goal:** consultants can upload sources, paste URLs, set the trust tier explicitly. The Source Rail and the firm-wide `/library` page both work.

**Backend:**
- Add `trust_level` column on `sources` table — enum `firm_vetted | credible_external | web_general | contested`. Default inferred from source type (web → web_general, document → firm_vetted) but user-overridable.
- New `PATCH /api/sources/{id}` to update `trust_level` + `title` + manual notes.
- Engagement-scoped vs firm-wide: `Source.scope = engagement | firm`. Firm-wide sources visible across engagements (will become the Library backbone).
- `GET /api/library/sources` — firm-wide sources for the workspace.

**Frontend:**
- New components in `components/workspace/AddSourcePanel.tsx` — upload area, URL input, trust-tier selector. Slides in from the bottom of the Source Rail.
- `app/library/page.tsx` (currently a stub) becomes a real source-library view: filterable list, drag-and-drop upload, trust-tier badges editable inline.
- "Pin to engagement" / "Exclude from queries" actions on each source row.

**Deliverable test:** upload a 10-K filing, set trust to `credible_external`. Open another engagement; the source is visible in the Library tab; pin it to the new engagement; query against it.

---

## Phase 6 — Hybrid retrieval (pgvector + Postgres `tsvector`)

**Goal:** pure semantic search misses ticker symbols, dates, exact names. Add keyword search side-by-side. (Real OpenSearch is v1 — `tsvector` is good enough for MVP.)

**Backend:**
- Migration `016_chunks_fts.sql` — add `tsvector` column on `chunks` with a trigger that auto-populates from `content`. GIN index for fast keyword search.
- New `backend/core/retrieval.py` `hybrid_search(session_id, query, top_k=20)` — runs vector search (top 30) + keyword search (top 30), reciprocal-rank-fusion merge to top 20.
- Permission filter applied as a SQL `WHERE` before the rank fusion (no leaking across engagements).
- Optional rerank step gated on `COHERE_API_KEY` being set — falls back gracefully when missing.

**Frontend:**
- The Source Rail's search bar now hits `/api/sources/search` with a `?q=` and shows results inline (semantic + keyword combined). Match highlighting on the snippet.
- The "Asking across" chip in the composer footer reflects whether keyword-only mode is active.

**Deliverable test:** query "GLP-1 2030" against a SaaS deck collection. Pure semantic returns generic chunks; hybrid surfaces the slide that says "GLP-1 SEA market 2030". Verify both top-k lists in the API response.

---

## Phase 7 — LiteLLM + OpenAI primary with structured citations via Instructor

**Goal:** all model calls go through one abstraction (LiteLLM). Output is forced to a structured citation schema, not free-form prose. (One provider — OpenAI — is wired in MVP. v1 adds Anthropic/Gemini/Grok by config only.)

**Backend:**
- Add `litellm` and `instructor` to `requirements.txt`.
- Refactor `backend/core/inference/` to call `litellm.acompletion()` instead of the OpenAI SDK directly. Provider routing via `models.yaml` (already exists) — `provider: openai` for MVP.
- Define Pydantic citation schema:
  ```py
  class Claim(BaseModel):
      span: tuple[int, int]
      chunk_ids: list[str]
      confidence: float
  class Section(BaseModel):
      text: str
      claims: list[Claim]
  class StructuredAnswer(BaseModel):
      tldr: str
      sections: list[Section]
      caveats: str
  ```
- Writer agent rewritten to use `instructor.from_litellm()` and return a `StructuredAnswer` — every claim references real `chunks.id` values (validated on parse, downgrade-confidence on mismatch).
- Cost tracking: LiteLLM's per-call cost recorded into a new `llm_calls` table (model, prompt_tokens, completion_tokens, usd_cost, session_id, user_id, ts).

**Frontend:**
- The conversation pane already renders citations from claim_support — wired to read the new structured-answer shape directly. The brittle "match claim_id to evidence_id" plumbing goes away.

**Deliverable test:** run a query, inspect the writer's raw output — it's a `StructuredAnswer` JSON with chunk-level citations on every claim. Frontend renders inline `[N]` markers from those chunk IDs.

---

## Phase 8 — NLI citation verifier (the moat)

**Goal:** every claim is checked: does the cited chunk actually support it? This is what stops citation hallucination. Per the brief: *"citation hallucination is the failure mode that kills the product."*

**Backend:**
- Add `nli_verifier` module. Two implementation paths, env-toggled:
  1. **Hosted (default for MVP):** HuggingFace Inference API with `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` — three-class entailment. Requires `HUGGINGFACE_API_KEY`.
  2. **Local (optional):** `sentence-transformers` cross-encoder loaded on worker boot. Slower first call, no API cost.
- Pipeline change: after the writer returns `StructuredAnswer`, every (claim, chunk) pair runs through NLI. Outcomes:
  - `entailment` → confidence stays
  - `neutral` → confidence × 0.6, mark "weak"
  - `contradiction` → confidence → 0, mark "unsupported", surface as a critical caveat
- Persist NLI scores into `claim_support_rows` (`nli_label`, `nli_confidence`).

**Frontend:**
- Citation marker color + popover label reflect NLI outcome — a chunk that contradicts its claim renders the marker red regardless of source trust.
- The CaveatBanner gains a row: "N citations failed entailment — review before delivery."

**Deliverable test:** craft a prompt that pushes the model to fabricate. Confirm the NLI verifier flags it. Confirm the UI shows the contradiction badge.

---

## Phase 9 — TipTap memo editor + DOCX export with citations

**Goal:** the memo artifact is a real editable document, not markdown. Exports to DOCX with citations as proper footnotes.

**Backend:**
- Migration `017_artifacts.sql` — proper `artifacts` table (id, engagement_id, type: `memo|deck|model|chart`, title, status: `draft|review|final`, document_json JSONB, updated_by, updated_at). Decouples artifacts from `reports`.
- New `POST /api/artifacts` to create a memo from the current conversation (LLM call to structure the memo).
- `POST /api/artifacts/{id}/export?format=docx` — uses `python-docx` to render the document tree.
  - Citations rendered as numbered footnotes using `python-docx-ng` or manual XML.
  - Source-list appendix at the end with full provenance.

**Frontend:**
- Add `tiptap` + `@tiptap/extension-mention` to `frontend/package.json`. Memo editor lives in the Artifacts Rail's center-pane takeover (Canvas mode).
- Custom TipTap extension `CitationMark` — wraps any text span with a chunk-id reference; renders as inline `[N]` with the same hover popover.
- Artifact list shows real artifacts from the new table, not derived stubs. Status pill (`Draft | Review | Final`) is editable.
- Export menu actually downloads a `.docx`.

**Deliverable test:** create a memo from a finished engagement. Edit a paragraph inline. Click a citation in the editor → popover works. Export → open the DOCX in Word; footnotes render correctly with full source titles.

---

## Phase 10 — Audit log + eval harness

**Goal:** every action is auditable (compliance table-stakes). Every release is regression-tested against a golden set (the brief says: *"Build this early or you'll regress every release"*).

**Backend (audit):**
- Migration `018_audit_log.sql` — append-only `audit_events` table (id, tenant_id, actor_id, action, resource_type, resource_id, payload JSONB, ip, user_agent, ts). Postgres-level: revoke `DELETE` and `UPDATE` from the application user.
- FastAPI middleware writes an audit row on every API call (action, resource, actor).
- Critical actions also log payload diffs: `source.upload`, `source.classify`, `artifact.create`, `artifact.export`, `engagement.run_pipeline`.
- New admin route `GET /api/admin/audit?engagement_id=...` — dumps audit trail for an engagement.

**Backend (eval):**
- New `backend/eval/` package + `backend/eval/golden/` directory of golden test cases.
- Each golden case is `{prompt, sources_dir, expected_claims, expected_citations}`. Start with the Germany-vs-France case + 4 more (one M&A, one growth-strategy, one with deliberately-conflicting sources, one with a deliberately-fabricatable hook).
- `pytest backend/eval/test_golden.py` runs each case end-to-end, scores citation faithfulness (% claims with NLI-entailed chunks), recommendation specificity (regex against banned generic phrases), and run cost.
- CI gate: a regression in citation faithfulness fails the build.

**Frontend (audit):**
- New `app/(admin)/audit/page.tsx` for engagement leads — read-only timeline of every action on the engagement.

**Deliverable test:** run the golden suite, see the report. Tamper with a writer prompt to encourage hallucination, see the eval fail in CI. Review the audit log of the demo engagement and confirm every action is recorded.

---

## Order of execution + estimated effort

| Phase | Name | Why this order |
|-------|------|----------------|
| 1 | Auth | Foundation — everything else assumes a current user |
| 2 | Engagement permissions | Required before any multi-user feature |
| 3 | S3 / MinIO | Required before Phase 4 evolves the chunk model |
| 4 | Chunk-level data model | Spine of the citation system |
| 5 | Source library UI | Now we have somewhere to put uploaded sources |
| 6 | Hybrid retrieval | Doesn't matter until chunks exist |
| 7 | LiteLLM + structured citations | Needs chunks to reference |
| 8 | NLI verifier | Validates the structured citations from Phase 7 |
| 9 | TipTap memo + DOCX | Now we have a verified citation system to attach to artifacts |
| 10 | Audit + eval | Done last so the audit log captures real actions and the eval harness scores a complete pipeline |

Effort: each phase is roughly the size of one of the UI-redesign phases. Plan on me sending you a working slice at the end of each one, you boot it, you tell me what's broken, I iterate. Don't expect all 10 today — that's compressed even for a tight build.

---

# Runbook — what YOU need to do

For the build to actually run end-to-end, here's the complete list of accounts, keys, and one-time setup you need on your end.

## 1. API keys

| Service | Used for | When needed | How to get it |
|---------|----------|-------------|---------------|
| **OpenAI** | Primary model (GPT-4o / GPT-4o-mini) for all agent calls + embeddings | ✅ Already in `.env` | Already done. The key in `.env` works. |
| **HuggingFace** | NLI inference for citation verification (Phase 8) | New | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) → "New token" → "Read" role → copy. Free tier is enough for MVP. |
| **SerpAPI** | Web research (researcher agent) | ✅ Already in `.env` | Already done. |
| Anthropic / xAI / Google | NOT USED in MVP | v1 only | Skip for now. |
| Cohere / Voyage | Optional rerank | Skip for MVP | Skip — `tsvector` hybrid is good enough. |
| WorkOS | SSO | v1 only | Skip — MVP is email/password. |

## 2. Software you need installed locally

| Tool | Why | Check |
|------|-----|-------|
| **Docker Desktop** | All services (Postgres, Redis, MinIO, backend, worker) | ✅ Already running |
| **Node.js 20+** | Frontend dev server | ✅ Already installed |
| **Git** | Pushing to your GitHub | ✅ Already configured |
| **Python 3.11** | Optional — only if you want to run backend tests outside Docker | ✅ Already installed |

## 3. Files you should prepare ahead

For Phase 4 / 5 testing, prepare:
- **One PDF** (10–30 pages, can be a public 10-K filing or industry report)
- **One expert call transcript** (any txt/markdown with `Speaker A:` / `Speaker B:` patterns + timestamps)
- **One or two URLs** to news articles or research pages

For Phase 9 testing:
- A **DOCX template** if your firm has a brand-specific memo style. Otherwise I'll generate a clean default.

For Phase 10 (eval set):
- **5 strategic questions** you'd realistically ask Argus (any topic)
- For each, **2–5 source documents** to ground the answer

## 4. One-time setup before we start

```bash
# 1. Make sure the demo currently runs (sanity check)
cd /c/Users/yassi/OneDrive/Desktop/Argus
docker compose -f docker-compose.yml up -d
# open http://localhost:3000 — confirm engagements home shows up

# 2. Add the HuggingFace token to .env (when we get to Phase 8)
echo "HUGGINGFACE_API_KEY=hf_your_token_here" >> .env
```

## 5. Things to decide before each phase starts

| Phase | Decision needed from you |
|-------|--------------------------|
| Phase 1 | Should self-registration be open, or admin-invite only? (MVP recommendation: invite-only via a `signup_codes` table — saves a lot of hardening) |
| Phase 4 | Aggressive parser (paid LlamaParse) or free Unstructured.io? (MVP recommendation: free PyMuPDF — good enough for a design partner, swap to LlamaParse in v1) |
| Phase 8 | Hosted HF (default, easy) or local NLI (cheaper at scale, more setup)? (MVP recommendation: hosted HF) |
| Phase 9 | Do you have a corporate DOCX template? |
| Phase 10 | Provide the 5 golden questions when we get there |

## 6. After each phase

- I commit the phase to a feature branch and push.
- You boot it locally and click through the deliverable test from the phase.
- You tell me what's broken or what you want changed.
- We iterate on that phase until it's solid before starting the next.

## 7. By the end of all 10 phases

You'll have:
- A logged-in workbench with multi-user engagements
- Real document upload + chunking + retrieval
- Verified citations grounded in actual source passages
- Editable memo artifact with DOCX export
- An audit log a compliance team can read
- A regression eval suite that fails the build on quality drops
- A foundation that v1 (multi-AI, real connectors, SSO, SOC 2) can be added to without rewrites

That's the MVP. One design partner can run a real engagement on it.

---

## Phase tracking

I'll mark phases here as they ship. None done yet:

- [x] Phase 1 — Auth ✅
- [x] Phase 2 — Engagement memberships + permissions ✅
- [x] Phase 3 — S3 / MinIO blob storage ✅
- [x] Phase 4 — Chunk-level data model + section-aware chunking ✅
- [x] Phase 5 — Source library UI ✅
- [x] Phase 6 — Hybrid retrieval ✅
- [x] Phase 7 — LiteLLM + OpenAI + structured citations ✅
- [x] Phase 8 — NLI citation verifier ✅
- [x] Phase 9 — TipTap memo + DOCX export ✅
- [x] Phase 10 — Audit log + eval harness ✅

# 🎉 MVP COMPLETE — all 10 phases shipped.

The system delivers what the brief asked for: one design partner can run a real engagement, get a verified citation-backed report, edit it inline, and export a client-ready DOCX.
