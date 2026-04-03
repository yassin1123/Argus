# Argus — package guide (for `argus.zip` recipients)

**You extracted `argus.zip`.** Read **`README.md`** first for what Argus is and how it fits together; use **this file** for runbook detail, repo organization, APIs, migrations, and troubleshooting. **`ARCHIVE.txt`** is a short manifest.

---

## 1. What you have

| Path | Purpose |
|------|---------|
| **`docker-compose.yml`** | **Recommended:** Postgres (pgvector), Redis, FastAPI API, Celery worker |
| **`backend/`** | FastAPI app, Celery task, multi-agent pipeline, DB layer, inference layer, PDF/PPTX deliverables, tests |
| **`frontend/`** | Next.js 14 (App Router) + Tailwind — workspace UI (evidence / answer / trust), light theme |
| **`backend/db/migrations/`** | SQL applied on **first** Postgres container init (`docker-entrypoint-initdb.d`) |
| **`.env.example`** | **Template only** — copy to `.env` (repo root) and `frontend/.env.local`; **never** commit real keys |
| **`README.md`** | Product story, diagram, example output, stack, run commands |
| **`ARCHIVE.txt`** | One-page checklist + layout |
| **`START_HERE.txt`** | Ultra-short pointer (which files to read first) |
| **`CODEBASE_OVERVIEW.md`** | Folder roles + request path + “where to change X” table |
| **`tools/package_argus_zip.py`** | Rebuild `argus.zip`: `python tools/package_argus_zip.py` |
| **`tools/smoke_check.sh`** | Optional health check (Compose up): `bash tools/smoke_check.sh` |
| **`tools/wslconfig.example`** | Optional WSL2 limits for Docker Desktop on Windows |

**Not in the zip (normal):** `node_modules/`, Python venv, `.next/`, `.env` / `.env.local`, database Docker volumes, `.git`. The packager **skips** `.env*` files except `.env.example` / `.env.sample` so local secrets are not archived by mistake.

---

## 2. Run the system (end-to-end)

### Prerequisites

- **Docker Desktop** (or Docker Engine + Compose plug-in)
- **Node.js 20+** (for the frontend dev server)
- An **OpenAI API key** (`OPENAI_API_KEY`)

### Backend (Docker)

From the folder that contains **`docker-compose.yml`** (the extracted root):

```bash
cp .env.example .env
```

Edit **`.env`**. **Minimum:** set `OPENAI_API_KEY=sk-...`.  
Compose wires `DATABASE_URL` / `REDIS_URL` for containers; the template’s `localhost` values are for **local** Python runs, not required when everything runs in Docker.

Start:

```bash
docker compose up --build
```

- API: **http://localhost:8000** — health: **http://localhost:8000/api/health** → `{"status":"ok"}`
- **First time** the Postgres **data volume** is created, scripts in **`backend/db/migrations/`** run in **filename order** (`001_…` through `010_…`).  
- **If you reuse an old Postgres volume** from a previous Argus version, new tables/columns may be missing. Apply any **new** `.sql` files manually (see §5) or remove the volume for a clean install.

### Frontend (local Node)

Second terminal:

```bash
cd frontend
cp ../.env.example .env.local
```

Ensure **`frontend/.env.local`** includes:

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Then:

```bash
npm install
npm run dev
```

Open **http://localhost:3000** → enter your question (optional URL/files in the composer) → you are routed to **`/sessions/{id}/intake`** for a short structured Q&A → submitting intake **starts the pipeline** and lands you on the workspace. From the workspace header you can open **Chat** (`/sessions/{id}/chat`) for follow-ups; the conversation agent may enqueue another pipeline run. The UI loads session state from **`GET /api/workspaces/{id}`**, polls every **3 seconds** while running, and may open **SSE** (`/api/workspaces/{id}/events`) during `processing`.

### Terminal smoke (curl)

With Compose up and `OPENAI_API_KEY` set:

```bash
curl -s -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"query":"Should a UK startup expand to Germany or France first?","title":"EU expansion"}'

# Replace SESSION_ID from the response:
curl -s -X POST http://localhost:8000/api/sessions/SESSION_ID/run
curl -s http://localhost:8000/api/workspaces/SESSION_ID
```

PowerShell:

```powershell
$body = '{"query":"Should a UK startup expand to Germany or France first?","title":"EU"}'
$r = Invoke-RestMethod -Method POST -Uri http://localhost:8000/api/sessions -ContentType "application/json" -Body $body
Invoke-RestMethod -Method POST -Uri "http://localhost:8000/api/sessions/$($r.session_id)/run"
```

### Backend without Docker

Possible on Linux/macOS with Postgres 15+ (pgvector), Redis, Python 3.11+. On **Windows**, PDF export (WeasyPrint) is painful on the host — **use Docker for the API** if you need PDFs.

---

## 3. How to read the codebase

### 3.1 User-visible flow

1. **Home** (`frontend/app/page.tsx`, `components/home/ComposerCard.tsx`) → `POST /api/sessions` (draft), optional `POST /api/inputs/upload` or `/url` → **`router.push` to `/sessions/{id}/intake`**.
2. **Intake** (`frontend/app/sessions/[id]/intake/page.tsx`) → `POST /api/sessions/{id}/intake/generate` (questions) → user answers → `POST /api/sessions/{id}/intake/submit` → **`POST /api/sessions/{id}/run`** → Celery runs **`backend/agents/orchestrator.py`** (`run_pipeline`). Planner sees intake context from DB (`backend/agents/planner.py`, orchestrator).
3. **Workspace** (`frontend/app/sessions/[id]/page.tsx`) → **`GET /api/workspaces/{id}`** + poll + optional SSE. Trust panel can **Run again** (`POST /api/sessions/{id}/run`). **Chat** → `frontend/app/sessions/[id]/chat/page.tsx` → `GET|POST /api/sessions/{id}/chat` (`backend/api/chat.py`, `agents/conversation.py`); may call **`run_partial_pipeline_task`** (full re-run with optional focus suffix today — see `backend/tasks/pipeline.py`).
4. **Exports** (when complete and a report exists) → `GET /api/exports/pdf|memo|report|pptx/{session_id}` (cached by content hash after first generation).

Re-running when status is **`failed`**, **`insufficient`**, or **`complete`** clears prior pipeline artifacts for that session before a new run.

### 3.2 Backend — open these first

| Area | Files |
|------|--------|
| App entry | **`backend/main.py`** — routers, CORS, DB pool lifespan |
| HTTP API | **`backend/api/sessions.py`**, **`backend/api/chat.py`**, **`backend/api/workspace.py`**, **`backend/api/inputs.py`**, **`backend/api/exports.py`** |
| Jobs | **`backend/tasks/pipeline.py`** — Celery **`run_pipeline_task`** |
| Pipeline | **`backend/agents/orchestrator.py`** — planner → research → analyst → critic → gates → verifier → writer → persistence |
| Inference | **`backend/core/inference/`** — `generate.py`, `structured.py`, `usage.py`, `exceptions.py`, `repair.py`, `registry.py`; models/tasks in **`backend/core/model_router.py`**, **`backend/config/models.yaml`** |
| Legacy LLM helper | **`backend/core/llm.py`** — lower-level calls; agents increasingly use the inference package |
| DB | **`backend/db/queries.py`**, **`backend/db/migrations/*.sql`** |
| Trust / labels | **`backend/core/trust_labels.py`**, **`backend/models/trust.py`**, metadata **`trust_object`** merged in orchestrator |
| Presentation DTOs | **`backend/models/workspace_dto.py`**, **`backend/presentations/workspace.py`** |
| Deliverables | **`backend/deliverables/`** — `blueprint.py`, `report_blueprint.py`, `deck_blueprint.py`, PDF/PPTX renderers |
| Config | **`backend/config/consulting_modes.yaml`**, **`backend/config/reasoning_skeletons.yaml`** |

### 3.3 Frontend — open these first

| Area | Files |
|------|--------|
| Layout / tokens | **`frontend/app/layout.tsx`**, **`frontend/styles/tokens.css`**, **`frontend/tailwind.config.ts`**, **`frontend/app/globals.css`** |
| Home | **`frontend/app/page.tsx`**, **`frontend/components/home/`** |
| Session workspace | **`frontend/app/sessions/[id]/page.tsx`**, **`frontend/app/sessions/[id]/intake/page.tsx`**, **`frontend/app/sessions/[id]/chat/page.tsx`**, **`frontend/components/sessions/`** |
| Report body | **`frontend/components/Report/`** |
| API + types | **`frontend/lib/api.ts`**, **`frontend/lib/types.ts`** |

### 3.4 Tests

```bash
cd backend
pip install -r requirements.txt
pytest tests -q
```

---

## 4. API quick reference

| Method | Path | Notes |
|--------|------|--------|
| POST | `/api/sessions` | Create draft (`query`, optional `title`, `report_mode`) |
| POST | `/api/sessions/{id}/run` | Enqueue pipeline (`409` if already `processing`) |
| POST | `/api/sessions/{id}/intake/generate` | Generate intake questions (JSON) |
| POST | `/api/sessions/{id}/intake/submit` | Persist intake answers (`id` + `answer` pairs) |
| GET | `/api/sessions/{id}/chat` | List conversation turns |
| POST | `/api/sessions/{id}/chat` | Send message; may enqueue worker (`processing`) |
| GET | `/api/sessions/{id}` | Raw session detail (DB-oriented) |
| GET | `/api/workspaces/{id}` | **Primary for UI:** detail + **`presentation`** (labels, rails) |
| GET | `/api/workspaces/{id}/events` | **SSE:** stream of `pipeline_events` rows (poll inside server ~1s) |
| GET | `/api/workspaces/{id}/evidence` | Smaller slice: evidence presentation + `evidence_objects` |
| POST | `/api/inputs/upload` | Multipart: `session_id`, `file` |
| POST | `/api/inputs/url` | JSON `{ "url", "session_id" }` |
| GET | `/api/exports/pdf/{id}` | Full PDF (cached) |
| GET | `/api/exports/memo/{id}` | Memo PDF (cached) |
| GET | `/api/exports/report/{id}` | Client PDF (cached) |
| GET | `/api/exports/pptx/{id}` | Deck (cached) |

---

## 5. Database migrations (important)

**Fresh Docker volume:** migrations **`001`–`010`** apply automatically in order (alphabetically / `docker-entrypoint-initdb.d` filename order).

**Existing volume:** if you upgraded from an older zip, run **only** the `.sql` files you have not applied yet (same numeric order as filenames). Common gaps:

| File | What it adds |
|------|----------------|
| **`007_pipeline_events.sql`** | `pipeline_events` — live progress / SSE |
| **`008_export_artifact_cache.sql`** | Export byte cache |
| **`009_intake_answers.sql`** | `intake_questions` / `intake_answers` on `sessions` |
| **`010_conversation_turns.sql`** | `conversation_turns` table for chat |

Earlier files (`001`–`006`) should already exist on older installs; only run a file if its objects are missing (`psql` error “already exists” on idempotent bits is often safe to ignore if you use `IF NOT EXISTS` patterns — prefer reading each file once).

Example (host with `psql`, adjust URL; run **in order** for your missing files):

```bash
psql "$DATABASE_URL" -f backend/db/migrations/007_pipeline_events.sql
psql "$DATABASE_URL" -f backend/db/migrations/008_export_artifact_cache.sql
psql "$DATABASE_URL" -f backend/db/migrations/009_intake_answers.sql
psql "$DATABASE_URL" -f backend/db/migrations/010_conversation_turns.sql
```

If **`007`** is absent, pipeline event inserts may no-op; without **`008`**, export cache misses (PDF/PPTX still generate). Without **`009`**, intake endpoints/queries may error. Without **`010`**, chat endpoints error.

---

## 6. Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Blank page / CORS | `NEXT_PUBLIC_API_URL`, **`ALLOWED_ORIGINS`** in `.env` includes your frontend origin |
| Stuck `processing` | Worker container logs, Redis, `OPENAI_API_KEY` |
| SSE not updating UI | Polling still runs every 3s; check browser devtools Network for `/events` |
| PDF fails on Windows host | Run API in Docker |
| DB errors after upgrade | §5 — apply **`007`–`010`** (whichever your volume lacks) |
| Chat or intake 500s | Confirm **`009`** / **`010`** applied; check API logs |
| `npm install` fails | Node 20+; delete `frontend/node_modules` and `frontend/.next`, reinstall |

---

## 7. Security

Do **not** share **`.env`** or **`.env.local`**. This archive is built **without** secret env files (see packager rules in **`tools/package_argus_zip.py`**).

---

## 8. Regenerate `argus.zip`

From the project root (folder with `docker-compose.yml`):

```bash
python tools/package_argus_zip.py
```

Overwrites **`argus.zip`**. Requires Python 3 only.

---

For the product narrative (problem, insight, diagram, example output), use **`README.md`**. For curl smoke tests, see **§2** above.
