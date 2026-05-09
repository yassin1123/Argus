"""Phase 2 / Week 6 / Day 5 regression: ``get_session_row`` must surface
``firm_id`` so the orchestrator's ``resolve_mode(... firm_id=...)``
call at the top of ``run_pipeline`` can find the firm override.

Without this, the orchestrator passes ``firm_id=None`` to the resolver,
the resolver can't find the firm row, and a session that should run
under a custom firm-defined mode silently falls through to the legacy
YAML path. We caught this in the W6/D5 e2e demo where Run A's writer
overlay never applied — the gate trivially passed because resolver
fell back to `general`.
"""

from __future__ import annotations

import uuid

import pytest


pytest.importorskip("asyncpg")


@pytest.fixture(autouse=True)
async def _db_pool():
    from db.connection import close_db, init_db

    await init_db()
    try:
        yield
    finally:
        await close_db()


async def test_get_session_row_includes_firm_id() -> None:
    from db.connection import acquire
    from db.queries import get_session_row

    DEFAULT_FIRM = "00000000-0000-0000-0000-000000000001"
    sid = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (
                id, title, query, status, report_mode, pipeline_state,
                metadata, gap_report, intake_questions, intake_answers,
                firm_id, updated_at
            ) VALUES (
                $1::uuid, 'd5 fix test', 'q', 'draft', 'general', 'idle',
                '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb,
                $2::uuid, NOW()
            )
            """,
            sid, DEFAULT_FIRM,
        )
    try:
        sess = await get_session_row(sid)
        assert sess is not None
        # The bug was: this key was missing from the return dict.
        assert "firm_id" in sess, sess.keys()
        assert sess["firm_id"] == DEFAULT_FIRM
    finally:
        async with acquire() as conn:
            await conn.execute("DELETE FROM sessions WHERE id = $1::uuid", sid)
