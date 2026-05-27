import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

load_dotenv()

from api import auth as auth_router
from api import admin, artifacts, audit_export as audit_export_router, chat, collaboration, comments, cost as cost_router, engagements, evaluations, exports, firm_library, firm_modes, inputs, metrics as metrics_router, notification_preferences, notifications as notifications_router, observability_dashboard as dashboard_router, reports, retention as retention_router, review, section_deepening, session_exports, sessions, sources, trace as trace_router, users, versioning as versioning_router, workspace
from audit.middleware import audit_middleware
from auth.dependencies import get_current_user
from core.limits import limiter
from core.model_router import resolve as _resolve_task_model
from core.provider_family import assert_cross_family
from db.connection import close_db, init_db

from core.logging_config import configure_json_logging
from core.observability.logging import configure_event_logging
from core.observability.middleware import trace_middleware

configure_json_logging()
configure_event_logging()

# Cross-family verification wedge: the analyst (synthesis) and verifier (judge)
# must resolve to different provider families (see backend/core/provider_family.py).
# We assert at module load — after model_router._load_yaml() is triggered by
# resolve() — so a misconfigured models.yaml or a same-family ARGUS_MODEL_*
# override crashes the container on boot rather than silently degrading
# verification quality. The DEMO_MODE bypass and unit-test environments don't
# spin up FastAPI through main.py, so this hook never blocks tests.
_analyst_cfg = _resolve_task_model("analyst")
_verifier_cfg = _resolve_task_model("verifier")
assert_cross_family(_analyst_cfg.model, _verifier_cfg.model)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Best-effort bucket bootstrap. If MinIO/S3 is unreachable on boot we still
    # serve health + auth + read endpoints so the app doesn't crash-loop.
    try:
        from storage.blob import ensure_bucket
        ensure_bucket()
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("blob bucket bootstrap failed: %s", e)
    yield
    await close_db()


app = FastAPI(title="Argus API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
allow_origins = [o.strip() for o in _origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Phase 5 / W20 D1: seed trace_id + emit request.start/.complete.
# Installed BEFORE audit so audit rows are written inside the same
# trace's contextvar scope (the orchestrator + DB layer will read
# from it automatically across await boundaries).
app.middleware("http")(trace_middleware)
# Phase 10: append-only audit log on every API call.
app.middleware("http")(audit_middleware)

# Auth routes are public.
app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])

# Everything else requires an authenticated user (or DEMO_MODE bypass).
PROTECTED = [Depends(get_current_user)]
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"], dependencies=PROTECTED)
app.include_router(chat.router, prefix="/api/sessions", tags=["chat"], dependencies=PROTECTED)
app.include_router(section_deepening.router, prefix="/api/sessions", tags=["section-deepening"], dependencies=PROTECTED)
app.include_router(review.router, prefix="/api/sessions", tags=["review"], dependencies=PROTECTED)
# Comments router declares its own path prefixes (``/sessions/{id}/comments`` AND
# ``/comments/{id}/...``), so it mounts at ``/api`` rather than a single sub-tree.
app.include_router(comments.router, prefix="/api", tags=["comments"], dependencies=PROTECTED)
app.include_router(users.router, prefix="/api/users", tags=["users"], dependencies=PROTECTED)
# Collaboration router declares its own per-endpoint prefixes
# (``/me/work``, ``/sessions/{id}/work``, ``/sessions/{id}/tasks``,
# ``/tasks/{id}/complete``) so it mounts at ``/api``.
app.include_router(collaboration.router, prefix="/api", tags=["collaboration"], dependencies=PROTECTED)
# W18/D3 — notification preferences. Mounted at /api so the router's
# own ``/me/notification-preferences`` paths surface unchanged.
app.include_router(notification_preferences.router, prefix="/api", tags=["notifications"], dependencies=PROTECTED)
# W18/D4 — notification inbox (bell + feed + read).
app.include_router(notifications_router.router, prefix="/api", tags=["notifications"], dependencies=PROTECTED)
# W19/D2 — payload version history (list + get + diff + restore).
app.include_router(versioning_router.router, prefix="/api", tags=["versioning"], dependencies=PROTECTED)
app.include_router(session_exports.router, prefix="/api/sessions", tags=["session-exports"], dependencies=PROTECTED)
app.include_router(engagements.router, prefix="/api/engagements", tags=["engagements"], dependencies=PROTECTED)
app.include_router(workspace.router, prefix="/api/workspaces", tags=["workspaces"], dependencies=PROTECTED)
app.include_router(evaluations.router, prefix="/api/evaluations", tags=["evaluations"], dependencies=PROTECTED)
app.include_router(reports.router, prefix="/api/reports", tags=["reports"], dependencies=PROTECTED)
app.include_router(inputs.router, prefix="/api/inputs", tags=["inputs"], dependencies=PROTECTED)
app.include_router(sources.router, prefix="/api/sources", tags=["sources"], dependencies=PROTECTED)
app.include_router(sources.library_router, prefix="/api/library", tags=["library"], dependencies=PROTECTED)
app.include_router(firm_library.router, prefix="/api/firms/{firm_id}/library", tags=["firm-library"], dependencies=PROTECTED)
app.include_router(firm_modes.router, prefix="/api/firms/{firm_id}/modes", tags=["firm-modes"], dependencies=PROTECTED)
app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"], dependencies=PROTECTED)
app.include_router(exports.router, prefix="/api/exports", tags=["exports"], dependencies=PROTECTED)
app.include_router(admin.router, prefix="/api/admin", tags=["admin"], dependencies=PROTECTED)
app.include_router(metrics_router.router, prefix="/api/admin", tags=["admin", "metrics"], dependencies=PROTECTED)
# W20/D3 cost API — engagement view on /api/sessions; firm + system-wide on /api/admin.
app.include_router(cost_router.session_router, prefix="/api/sessions", tags=["cost"], dependencies=PROTECTED)
app.include_router(cost_router.router, prefix="/api/admin", tags=["admin", "cost"], dependencies=PROTECTED)
# W20/D4 trace API — engagement view on /api/sessions; recent on /api/admin.
app.include_router(trace_router.session_router, prefix="/api/sessions", tags=["trace"], dependencies=PROTECTED)
app.include_router(trace_router.router, prefix="/api/admin", tags=["admin", "trace"], dependencies=PROTECTED)
# W20/D5 admin observability dashboard — joins D2 metrics + D3 cost + D4 trace.
app.include_router(dashboard_router.router, prefix="/api/admin", tags=["admin", "observability"], dependencies=PROTECTED)
# W23/D2 retention + right-to-deletion — POST /api/sessions/{id}/purge + firm admin.
app.include_router(retention_router.session_router, prefix="/api/sessions", tags=["retention"], dependencies=PROTECTED)
app.include_router(retention_router.router, prefix="/api/admin", tags=["admin", "retention"], dependencies=PROTECTED)
# W23/D3 audit export — firm-scoped, content-free CSV / NDJSON.
app.include_router(audit_export_router.router, prefix="/api/admin", tags=["admin", "audit-export"], dependencies=PROTECTED)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
