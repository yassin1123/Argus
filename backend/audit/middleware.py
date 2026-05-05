"""FastAPI middleware that audits every API call.

Writes a row into `audit_events` per request — best-effort, never raises.
Skips noisy reads (GET /api/health, internal poll endpoints) by default;
critical writes (POST/PATCH/DELETE/PUT) are always logged.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from fastapi import Request, Response

from audit.queries import append_event
from auth.sessions import COOKIE_NAME, lookup_session

logger = logging.getLogger(__name__)

# Action mapping for common (method, path-prefix) pairs.
def _classify_action(method: str, path: str) -> tuple[str, str | None]:
    """Return (action_label, resource_type) for the audit row."""
    p = path.rstrip("/")
    m = method.upper()
    if p.startswith("/api/auth/login"):
        return "auth.login", None
    if p.startswith("/api/auth/logout"):
        return "auth.logout", None
    if p.startswith("/api/auth/register"):
        return "auth.register", None
    if p.startswith("/api/auth/me"):
        return "auth.me", None
    if p.startswith("/api/sessions"):
        if m == "POST" and p == "/api/sessions":
            return "engagement.create", "engagement"
        if "/run" in p and m == "POST":
            return "engagement.run_pipeline", "engagement"
        if "/intake/submit" in p and m == "POST":
            return "engagement.intake_submit", "engagement"
        if m == "DELETE":
            return "engagement.delete", "engagement"
        return "engagement.read", "engagement"
    if p.startswith("/api/workspaces"):
        return "engagement.workspace_read", "engagement"
    if p.startswith("/api/engagements") and "/members" in p:
        if m == "POST":
            return "engagement.add_member", "engagement"
        if m == "DELETE":
            return "engagement.remove_member", "engagement"
        return "engagement.list_members", "engagement"
    if p.startswith("/api/sources") or p.startswith("/api/library"):
        if m == "PATCH":
            return "source.classify", "source"
        if m == "DELETE":
            return "source.delete", "source"
        return "source.read", "source"
    if p.startswith("/api/inputs/upload"):
        return "source.upload", "source"
    if p.startswith("/api/inputs/url"):
        return "source.url_ingest", "source"
    if p.startswith("/api/inputs/blobs/"):
        return "source.download", "source"
    if p.startswith("/api/artifacts"):
        if m == "POST" and p == "/api/artifacts":
            return "artifact.create", "artifact"
        if "/export" in p:
            return "artifact.export", "artifact"
        if m == "PATCH":
            return "artifact.edit", "artifact"
        if m == "DELETE":
            return "artifact.delete", "artifact"
        return "artifact.read", "artifact"
    if p.startswith("/api/exports"):
        return "report.export", "report"
    return f"{m.lower()}.{p}", None


# Paths we DON'T audit (too noisy, no security value).
_SKIP_PATHS = ("/api/health",)
# Read methods are recorded only for sensitive paths.
_SENSITIVE_READ_PREFIXES = (
    "/api/admin/",
    "/api/inputs/blobs/",  # downloads are sensitive
)


def _should_audit(method: str, path: str) -> bool:
    if any(path.startswith(s) for s in _SKIP_PATHS):
        return False
    m = method.upper()
    if m in ("POST", "PATCH", "PUT", "DELETE"):
        return True
    # GET: only audit sensitive prefixes
    if m == "GET" and any(path.startswith(p) for p in _SENSITIVE_READ_PREFIXES):
        return True
    return False


async def audit_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response: Response | None = None
    try:
        response = await call_next(request)
    finally:
        try:
            method = request.method
            path = request.url.path
            if response is not None and _should_audit(method, path):
                user_id = None
                user_email = None
                token = request.cookies.get(COOKIE_NAME)
                if token:
                    user = await lookup_session(token)
                    if user:
                        user_id = user["user_id"]
                        user_email = user["email"]
                action, resource_type = _classify_action(method, path)

                # Try to extract resource_id from path (last UUID-shaped segment).
                resource_id = None
                for seg in reversed(path.strip("/").split("/")):
                    if len(seg) == 36 and seg.count("-") == 4:
                        resource_id = seg
                        break

                ip = request.client.host if request.client else None
                ua = request.headers.get("user-agent")
                # Light payload — engagement_id when available.
                payload = {}
                qp_eng = request.query_params.get("engagement_id")
                if qp_eng:
                    payload["engagement_id"] = qp_eng

                await append_event(
                    action=action,
                    actor_user_id=user_id,
                    actor_email=user_email,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    method=method,
                    path=path,
                    status_code=response.status_code,
                    ip=ip,
                    user_agent=ua,
                    payload=payload,
                )
        except Exception as e:  # noqa: BLE001
            logger.debug("audit middleware skipped: %s", e)
    return response  # type: ignore[return-value]
