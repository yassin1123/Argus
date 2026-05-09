"""
Seed Postgres with demo engagements so the workspace is populated immediately
when DEMO_MODE=1. Idempotent — re-running clears prior demo rows by id.

Run inside the backend container:
    docker compose exec backend python scripts/seed_demo.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import asyncpg

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# Three seeded engagements. The first is a full case study; the others are
# stubs that show "lived-in" homepage state.
DEMO_SESSIONS = [
    {
        "fixture": "germany_vs_france",
        "full": True,
    },
    {
        "fixture": None,
        "full": False,
        "id": "33333333-3333-4333-8333-333333333333",
        "title": "Demo · M&A diligence — ExampleCo financials",
        "query": "Evaluate ExampleCo as an acquisition target given recent revenue compression and pending litigation.",
        "report_mode": "due_diligence",
        "metadata": {
            "client_label": "Demo · ExampleCo",
            "engagement_type": "Demo engagement",
            "demo": True,
            "stub": True,
        },
    },
    {
        "fixture": None,
        "full": False,
        "id": "44444444-4444-4444-8444-444444444444",
        "title": "Demo · Growth strategy — pricing model shift",
        "query": "Should we shift from seat-based to value-based pricing for our enterprise tier?",
        "report_mode": "growth_strategy",
        "metadata": {
            "client_label": "Demo · ExampleCo",
            "engagement_type": "Demo engagement",
            "demo": True,
            "stub": True,
        },
    },
]


def _load(fixture: str, name: str) -> Any:
    path = FIXTURES_DIR / fixture / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        sys.stderr.write("DATABASE_URL not set\n")
        sys.exit(2)
    return url


async def _clear_existing(conn: asyncpg.Connection) -> None:
    """Wipe prior demo rows so re-seeding is clean."""
    ids = [s.get("id") or _load(s["fixture"], "session")["id"] for s in DEMO_SESSIONS]
    await conn.execute("DELETE FROM sessions WHERE id = ANY($1::uuid[])", ids)


async def _insert_session_row(conn: asyncpg.Connection, session: dict[str, Any]) -> None:
    # Migration 024 made sessions.firm_id NOT NULL. Demo rows belong to
    # the default firm (deterministic UUID seeded by 024).
    await conn.execute(
        """
        INSERT INTO sessions (
            id, title, query, status, report_mode, pipeline_state,
            metadata, gap_report, intake_questions, intake_answers,
            firm_id, updated_at
        ) VALUES (
            $1::uuid, $2, $3, $4, $5, $6,
            $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb,
            '00000000-0000-0000-0000-000000000001'::uuid, NOW()
        )
        """,
        session["id"],
        session["title"],
        session["query"],
        session.get("status", "complete"),
        session.get("report_mode", "general"),
        session.get("pipeline_state", "done"),
        json.dumps(session.get("metadata") or {}),
        json.dumps(session.get("gap_report") or {}),
        json.dumps(session.get("intake_questions") or []),
        json.dumps(session.get("intake_answers") or []),
    )


async def _insert_evidence(conn: asyncpg.Connection, session_id: str, evidence: list[dict[str, Any]]) -> None:
    for e in evidence:
        await conn.execute(
            """
            INSERT INTO evidence_objects (
                id, session_id, task_id, claim, quote, source_title, source_url,
                source_date, source_type, source_score, confidence, is_inference
            ) VALUES (
                $1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
            )
            """,
            e["id"],
            session_id,
            e.get("task_id"),
            e.get("claim", ""),
            e.get("quote", ""),
            e.get("source_title", ""),
            e.get("source_url", ""),
            e.get("source_date"),
            e.get("source_type", "web"),
            float(e.get("source_score", 0.0)),
            e.get("confidence", "medium"),
            bool(e.get("is_inference", False)),
        )


async def _insert_report(conn: asyncpg.Connection, session_id: str, r: dict[str, Any]) -> str:
    consulting_payload = {
        "executive_insights": r.get("executive_insights", []),
        "recommendation_claim_ids": r.get("recommendation_claim_ids", []),
        "key_risks_structured": r.get("key_risks_structured", []),
        "decision_criteria": r.get("decision_criteria", []),
        "options_matrix": r.get("options_matrix", []),
        "kill_criteria": r.get("kill_criteria", []),
        "what_would_change_our_mind": r.get("what_would_change_our_mind", ""),
        "evidence_ledger_summary": r.get("evidence_ledger_summary", ""),
    }
    # Inline claim_support into the report JSONB so the workspace API surfaces it.
    claim_support_inline = r.get("_claim_support_inline") or []
    row = await conn.fetchrow(
        """
        INSERT INTO reports (
            id, session_id, recommendation, confidence_level, summary,
            key_reasons, risks, counterarguments, next_steps, sources, raw_output, caveats,
            evidence_bundle, verification, evidence_count, unsupported_claim_count,
            consulting_payload, reasoning_graph, claim_support
        ) VALUES (
            $1::uuid, $2::uuid, $3, $4, $5,
            $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11, $12,
            $13::jsonb, $14::jsonb, $15, $16, $17::jsonb, $18::jsonb, $19::jsonb
        )
        RETURNING id
        """,
        r["id"],
        session_id,
        r["recommendation"],
        r["confidence_level"],
        r["summary"],
        json.dumps(r.get("key_reasons", [])),
        json.dumps(r.get("risks", [])),
        json.dumps(r.get("counterarguments", [])),
        json.dumps(r.get("next_steps", [])),
        json.dumps(r.get("sources", [])),
        None,
        r.get("caveats", ""),
        json.dumps([]),
        json.dumps(r.get("verification", {})),
        int(r.get("evidence_count", 0)),
        int(r.get("unsupported_claim_count", 0)),
        json.dumps(consulting_payload),
        json.dumps(r.get("reasoning_graph", {})),
        json.dumps(claim_support_inline),
    )
    return str(row["id"])


async def _insert_claim_support_rows(
    conn: asyncpg.Connection,
    session_id: str,
    report_id: str,
    rows: list[dict[str, Any]],
) -> None:
    for row in rows:
        await conn.execute(
            """
            INSERT INTO claim_support_rows (
                session_id, report_id, claim_id, claim_text, evidence_object_ids,
                support_type, verifier_verdict, contradiction_flag, staleness_hint,
                entailment_score, weak_flag
            ) VALUES (
                $1::uuid, $2::uuid, $3, $4, $5::uuid[], $6, $7, $8, $9, $10, $11
            )
            """,
            session_id,
            report_id,
            row["claim_id"],
            row["claim_text"],
            row.get("evidence_object_ids", []),
            row.get("support_type", "inference"),
            row.get("verifier_verdict"),
            bool(row.get("contradiction_flag", False)),
            row.get("staleness_hint", ""),
            float(row.get("entailment_score") or 0.0),
            bool(row.get("weak_or_unsupported", False)),
        )


async def _insert_agent_outputs(
    conn: asyncpg.Connection,
    session_id: str,
    outputs: list[dict[str, Any]],
) -> None:
    for o in outputs:
        await conn.execute(
            """
            INSERT INTO agent_outputs (session_id, agent_name, input, output, duration_ms, token_count)
            VALUES ($1::uuid, $2, $3, $4, $5, $6)
            """,
            session_id,
            o.get("agent_name", ""),
            o.get("input"),
            o.get("output", ""),
            o.get("duration_ms"),
            o.get("token_count"),
        )


async def _insert_pipeline_events(
    conn: asyncpg.Connection,
    session_id: str,
    events: list[dict[str, Any]],
) -> None:
    for ev in events:
        await conn.execute(
            """
            INSERT INTO pipeline_events (session_id, event_type, stage, status, payload)
            VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
            """,
            session_id,
            ev.get("event_type", "trace"),
            ev.get("stage", ""),
            ev.get("status", ""),
            json.dumps(ev.get("payload") or {}),
        )


async def _seed_full(conn: asyncpg.Connection, fixture: str) -> None:
    session = _load(fixture, "session")
    evidence = _load(fixture, "evidence")
    report = _load(fixture, "report")
    claim_support = _load(fixture, "claim_support")
    agent_outputs = _load(fixture, "agent_outputs")
    pipeline_events = _load(fixture, "pipeline_events")

    await _insert_session_row(conn, session)
    await _insert_evidence(conn, session["id"], evidence)
    # Inline claim_support into the report JSONB so the workspace API surfaces it.
    report_with_cs = {**report, "_claim_support_inline": claim_support}
    report_id = await _insert_report(conn, session["id"], report_with_cs)
    await _insert_claim_support_rows(conn, session["id"], report_id, claim_support)
    await _insert_agent_outputs(conn, session["id"], agent_outputs)
    await _insert_pipeline_events(conn, session["id"], pipeline_events)
    print(f"  ✓ seeded full case study: {session['title']}")


async def _seed_stub(conn: asyncpg.Connection, stub: dict[str, Any]) -> None:
    await _insert_session_row(
        conn,
        {
            "id": stub["id"],
            "title": stub["title"],
            "query": stub["query"],
            "status": "draft",
            "report_mode": stub.get("report_mode", "general"),
            "pipeline_state": "idle",
            "metadata": stub.get("metadata", {}),
            "gap_report": {},
            "intake_questions": [],
            "intake_answers": [],
        },
    )
    print(f"  ✓ seeded stub engagement: {stub['title']}")


async def _seed_demo_user(conn: asyncpg.Connection) -> None:
    """Provision a `demo@argus.local` user so DEMO_MODE has someone to attach to.

    Login (when not using DEMO_MODE bypass):
      email:    demo@argus.local
      password: demo-password
    """
    try:
        from passlib.context import CryptContext
        ctx = CryptContext(schemes=["bcrypt"], bcrypt__rounds=10)
        demo_hash = ctx.hash("demo-password")
    except ImportError:
        # passlib not installed in this env — skip rather than crash.
        print("  · passlib unavailable — skipping demo user")
        return
    try:
        await conn.execute(
            """
            INSERT INTO users (email, password_hash, full_name, role)
            VALUES ('demo@argus.local', $1, 'Demo User', 'admin')
            ON CONFLICT (email) DO NOTHING
            """,
            demo_hash,
        )
        print("  ✓ ensured demo user (demo@argus.local / demo-password)")
    except asyncpg.UndefinedTableError:
        print("  · users table missing (run migrations) — skipping demo user")


async def main() -> int:
    print("Argus demo seeder")
    print(f"  fixtures: {FIXTURES_DIR}")

    conn = await asyncpg.connect(_database_url())
    try:
        await _seed_demo_user(conn)
        await _clear_existing(conn)
        for entry in DEMO_SESSIONS:
            if entry.get("full"):
                await _seed_full(conn, entry["fixture"])
            else:
                await _seed_stub(conn, entry)
    finally:
        await conn.close()

    print("Done. Open http://localhost:3000 to see seeded engagements.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
