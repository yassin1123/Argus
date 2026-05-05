import asyncio
import logging
import os

from celery import Celery

logger = logging.getLogger(__name__)

celery_app = Celery(
    "argus",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_soft_time_limit=300,
    task_time_limit=360,
    broker_connection_retry_on_startup=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1,
)


@celery_app.task
def run_pipeline_task(session_id: str) -> None:
    async def _run() -> None:
        from db.connection import close_db, init_db
        from db.queries import get_session_row

        await init_db()
        try:
            row = await get_session_row(session_id)
            if not row:
                raise RuntimeError(f"Session not found: {session_id}")
            query = row["query"]
            from agents.orchestrator import run_pipeline

            await run_pipeline(session_id, query)
        finally:
            await close_db()

    try:
        asyncio.run(_run())
    except Exception:
        logger.exception("Pipeline task failed for session %s", session_id)
        raise


@celery_app.task
def run_partial_pipeline_task(
    session_id: str,
    stages: list[str] | None = None,
    focus_query: str | None = None,
) -> None:
    """MVP: runs full pipeline with optional focus appended to query. `stages` reserved for future partial runs."""

    async def _run() -> None:
        from db.connection import close_db, init_db
        from db.queries import clear_pipeline_artifacts, get_session_row

        await init_db()
        try:
            row = await get_session_row(session_id)
            if not row:
                raise RuntimeError(f"Session not found: {session_id}")
            q = str(row.get("query") or "")
            if focus_query and str(focus_query).strip():
                q = f"{q}\n\n[Follow-up from chat: {str(focus_query).strip()[:2000]}]"
            await clear_pipeline_artifacts(session_id)
            from agents.orchestrator import run_pipeline

            await run_pipeline(session_id, q)
        finally:
            await close_db()

    _ = stages
    try:
        asyncio.run(_run())
    except Exception:
        logger.exception("Partial pipeline task failed for session %s", session_id)
        raise
