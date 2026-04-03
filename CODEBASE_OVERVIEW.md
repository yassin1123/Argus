# Argus codebase overview

Read this after **`START_HERE.txt`** and the first sections of **`ZIP_PACKAGE.md`**. It explains *what each major folder does* and *how data moves* so you can navigate the zip without guessing.

## Stack

```
Browser (Next.js)  →  FastAPI (:8000)  →  PostgreSQL (pgvector) + Redis
                              ↓
                        Celery worker  →  same DB/Redis, runs `run_pipeline` / chat follow-ups
```

- **PostgreSQL** holds sessions, reports, evidence, embeddings, pipeline events, chat turns, etc.
- **Redis** is the Celery broker/backend.
- **OpenAI** (required) drives agents; **SerpAPI** / **Cohere** are optional (see `.env.example`).

## Top-level folders

| Folder / file | Role |
|---------------|------|
| **`docker-compose.yml`** | Brings up `db`, `redis`, `backend` (API), `worker` (Celery). Mounts `backend/db/migrations` into Postgres init. |
| **`backend/`** | Python application: HTTP routers under `api/`, agent graph in `agents/` (start with `orchestrator.py`), DB access in `db/queries.py`, async tasks in `tasks/pipeline.py`. |
| **`frontend/`** | Next.js 14 App Router: pages under `app/`, UI under `components/`, API client and types in `lib/api.ts` and `lib/types.ts`. |
| **`tools/`** | `package_argus_zip.py` (release zip), `smoke_check.sh` (Compose smoke test), `e2e_pipeline.ps1`, `wslconfig.example`. |

## Request path (happy path)

1. **`POST /api/sessions`** — inserts a `sessions` row (`draft`).
2. **Intake** — `POST .../intake/generate` + `submit` writes JSON on the session; **`POST .../run`** sets status and enqueues Celery.
3. **Worker** — `run_pipeline(session_id, query)` in **`agents/orchestrator.py`**: planner → researcher → analyst → critic → verifier → writer → saves `reports`, `agent_outputs`, evidence rows, metadata.
4. **UI** — **`GET /api/workspaces/{id}`** returns a fat JSON plus a **`presentation`** object (human-readable labels). **`GET .../events`** streams pipeline rows for SSE.

## Where to change behavior

| Goal | Start here |
|------|------------|
| Prompts / model choice | `backend/config/models.yaml`, agent modules in `backend/agents/*.py` |
| API shape or new routes | `backend/api/`, register in `backend/main.py` |
| DB schema | New file in `backend/db/migrations/` (bump sequence); mirror queries in `db/queries.py` |
| Trust / rail labels | `backend/presentations/workspace.py`, `frontend/lib/formatters.ts` |
| UI layout / flows | `frontend/app/...`, `frontend/components/sessions/` |
| PDF/PPTX output | `backend/deliverables/` |

## Configuration

Copy **`.env.example`** to **`.env`** (Compose reads it for secrets) and to **`frontend/.env.local`** for `NEXT_PUBLIC_API_URL`. Never commit real keys.

## Tests

```bash
cd backend
pip install -r requirements.txt
pytest tests -q
```

For commands and curl samples, use **`README.md`**. For migrations on old DB volumes, **`ZIP_PACKAGE.md` §5**.
