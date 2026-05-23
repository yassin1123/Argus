"""Phase 3 / Week 14 / Day 3 — sample workspace seeder.

Builds a repeatable, fully-populated "Meridian Advisory" demo workspace
that double-purposes as the onboarding reference and the Phase 4
collaboration test fixture.

What gets seeded (all idempotent):

  - **Firm "Meridian Advisory"** (slug ``meridian-advisory``) with
    branding JSONB — primary + secondary colour, footer text, partner
    name / title for artifacts. Distinct from the existing
    ``argus-demo-boutique`` firm so demos can show a fresh-but-populated
    state.
  - **3 users** with bcrypt-hashed passwords and firm_memberships:
    Helena Voss (firm_admin / partner), Marcus Thorne (firm_member /
    senior consultant), Priya Shah (firm_member / junior analyst).
  - **Library content** — the W14/D2 expansion fixtures (UK SaaS
    primer, consumer-goods market sizing, M&A carve-out playbook, UK
    regulatory brief, diligence checklist template, comparable
    transactions CSV) ingested via the W14/D2 hardened bulk ingestion.
  - **Two engagements** (M&A Kestrel Logistics diligence +
    growth_strategy Halcyon Health expansion) restored from cached
    fixture JSON so the seeder NEVER calls the LLM pipeline by
    default. The cached fixtures contain hand-authored
    writer-payload-shaped output that demonstrates the system's
    end-state (the growth fixture includes a fully-populated Porter's
    Five Forces block so the W14/D1 fix path is visible end-to-end
    independent of the schema-enforcement carry-forward).
  - **Per-engagement six-artifact bundle** generated via the
    W10-W13 export pipeline (templates only, $0.00 LLM cost): 1-pager
    (HTML + PDF), deck (PPTX), Excel model (XLSX), cover email (MD +
    HTML + PDF), interview guide (MD + HTML + PDF).
  - **Section deepening history** — 2 deepening rows per engagement
    drawn from the fixture so the W9 deepening UI has history to
    surface.

Usage::

    python tools/seed_sample_workspace.py
    python tools/seed_sample_workspace.py --reset
    python tools/seed_sample_workspace.py --skip-artifacts

The seeder prints a per-firm summary at the end including the partner
login email + password (always the synthetic
``MeridianSample!2026``) so a manual smoke can immediately follow.

Hard rules (per W14/D3 spec): the seeder never re-runs the LLM
pipeline. ``--force-regenerate`` is reserved for a future variant
that calls ``run_pipeline`` — not implemented today because the
cached fixtures cover the demo + test surface.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

_FIXTURES = _REPO_ROOT / "backend" / "tests" / "fixtures" / "sample_workspace"
_LIBRARY_EXPANSION = _REPO_ROOT / "backend" / "tests" / "fixtures" / "library_expansion"

_FIRM_FIXTURE = "workspace.json"
_ENGAGEMENT_FIXTURES = ("engagement_m_and_a.json", "engagement_growth_strategy.json")


@dataclass
class SeederSummary:
    firm_id: str
    firm_slug: str
    user_ids: dict[str, str]
    library_chunks: int
    engagements: list[dict[str, Any]]
    artifacts_generated: int
    used_cache: bool


# ---------------------------------------------------------------------------
# Firm + users
# ---------------------------------------------------------------------------


async def _ensure_firm(spec: dict[str, Any]) -> str:
    from db.connection import acquire

    slug = spec["slug"]
    name = spec["name"]
    branding = spec.get("branding") or {}
    metadata = spec.get("metadata") or {}
    async with acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM firms WHERE slug = $1", slug)
        if row:
            await conn.execute(
                """
                UPDATE firms
                   SET name = $2,
                       branding = $3::jsonb,
                       metadata = $4::jsonb
                 WHERE slug = $1
                """,
                slug, name, json.dumps(branding), json.dumps(metadata),
            )
            return str(row["id"])
        row = await conn.fetchrow(
            """
            INSERT INTO firms (name, slug, branding, metadata)
            VALUES ($1, $2, $3::jsonb, $4::jsonb)
            RETURNING id
            """,
            name, slug, json.dumps(branding), json.dumps(metadata),
        )
        return str(row["id"])


async def _ensure_users(firm_id: str, users_spec: list[dict[str, Any]]) -> dict[str, str]:
    """Create (or update) each user + firm_membership. Returns
    ``{email: user_id}``."""
    # Use bcrypt directly — passlib 1.7.x has an incompat with bcrypt 5.x's
    # backend-detection test that fails before any user password is even
    # hashed. The production stack hits the same library; this seeder
    # short-circuits passlib to avoid the dev-only flake.
    import bcrypt as _bcrypt

    def hash_password(plaintext: str) -> str:
        return _bcrypt.hashpw(plaintext.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("ascii")

    from db.connection import acquire

    out: dict[str, str] = {}
    async with acquire() as conn:
        for spec in users_spec:
            email = spec["email"]
            existing = await conn.fetchrow(
                "SELECT id FROM users WHERE email = $1::citext", email,
            )
            if existing:
                user_id = str(existing["id"])
            else:
                pw_hash = hash_password(spec["password"])
                user_id = str(uuid.uuid4())
                await conn.execute(
                    """
                    INSERT INTO users (id, email, password_hash, full_name, role, default_firm_id)
                    VALUES ($1::uuid, $2, $3, $4, $5, $6::uuid)
                    """,
                    user_id,
                    email,
                    pw_hash,
                    spec.get("full_name") or "",
                    spec.get("system_role") or "member",
                    firm_id if spec.get("is_default_firm") else None,
                )
            # Membership upsert.
            await conn.execute(
                """
                INSERT INTO firm_memberships (firm_id, user_id, role)
                VALUES ($1::uuid, $2::uuid, $3)
                ON CONFLICT (firm_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """,
                firm_id, user_id, spec.get("firm_role") or "member",
            )
            # Ensure default_firm_id is set if requested (and was previously NULL).
            if spec.get("is_default_firm"):
                await conn.execute(
                    "UPDATE users SET default_firm_id = $1::uuid WHERE id = $2::uuid AND default_firm_id IS NULL",
                    firm_id, user_id,
                )
            out[email] = user_id
    return out


# ---------------------------------------------------------------------------
# Library ingestion (via W14/D2 hardened path)
# ---------------------------------------------------------------------------


async def _seed_library(firm_id: str) -> int:
    """Ingest the W14/D2 library expansion fixtures into the Meridian
    firm using the hardened ingestion path. Returns total chunks
    created across ``ready`` outcomes (``dedup_skipped`` rows
    contribute zero new chunks).
    """
    from core.firm_library.ingestion import _ingest_single_hardened

    # Same per-fixture metadata the W14/D2 seeder uses, kept inline so
    # the sample-workspace seeder doesn't depend on the W14/D2 seeder
    # module being importable.
    meta = {
        "uk_saas_sector_primer.md": (
            "UK SaaS Sector Primer", "sector_primer",
            ["growth_strategy", "market_entry"], ["saas", "uk"],
        ),
        "consumer_goods_market_sizing.md": (
            "Consumer Goods Market Sizing", "methodology",
            ["growth_strategy", "market_entry", "m_and_a_diligence"],
            ["consumer_goods", "uk"],
        ),
        "ma_carveout_playbook.md": (
            "M&A Carve-out & Divestiture Playbook", "playbook",
            ["m_and_a_diligence", "carve_out"], [],
        ),
        "regulatory_environment_brief.md": (
            "UK Regulatory Environment Brief", "framework",
            ["m_and_a_diligence", "growth_strategy", "market_entry"],
            ["uk", "regulatory"],
        ),
        "diligence_checklist_template.md": (
            "Diligence Checklist Template", "framework",
            ["m_and_a_diligence"], [],
        ),
        "comparable_transactions.csv": (
            "Comparable Transactions Database (UK, synthetic)", "prior_report",
            ["m_and_a_diligence"], ["uk", "comparables"],
        ),
    }
    total_new = 0
    for path in sorted(_LIBRARY_EXPANSION.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        m = meta.get(path.name)
        if m is None:
            continue
        title, cat, modes, sectors = m
        res = await _ingest_single_hardened(
            firm_id=firm_id,
            title=title,
            category=cat,
            file_bytes=path.read_bytes(),
            source_filename=path.name,
            uploaded_by=None,
            description=f"Meridian sample workspace — {cat}.",
            intended_modes=modes,
            sector_tags=sectors,
            trust_level="firm_vetted",
        )
        if res.status == "ready":
            total_new += res.chunks_created
    return total_new


# ---------------------------------------------------------------------------
# Engagement cache restore
# ---------------------------------------------------------------------------


async def _restore_engagement(
    firm_id: str,
    user_ids: dict[str, str],
    spec: dict[str, Any],
) -> dict[str, Any]:
    """Insert (or update) the session + report + evidence_objects +
    agent_outputs + section_deepening_runs that the W10-W13 export
    pipeline needs to render artifacts against the cached fixture.

    Idempotency: the session is keyed by (firm_id, title); a second run
    updates the existing session/report in place rather than creating
    duplicates.
    """
    from db.connection import acquire

    report = spec["report"]
    citations: list[dict[str, Any]] = spec.get("citations") or []
    deepenings: list[dict[str, Any]] = spec.get("deepenings") or []
    title = spec["title"]
    mode = spec["report_mode"]

    owner_email = spec.get("owner_email")
    owner_id = user_ids.get(owner_email) if owner_email else None
    team_ids = [user_ids[e] for e in (spec.get("team_emails") or []) if e in user_ids]

    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM sessions WHERE firm_id = $1::uuid AND title = $2",
            firm_id, title,
        )
        if row:
            session_id = str(row["id"])
            await conn.execute(
                """
                UPDATE sessions
                   SET query = $2,
                       status = 'deliverable_ready',
                       report_mode = $3,
                       pipeline_state = 'deliverable_ready',
                       metadata = $4::jsonb,
                       updated_at = NOW()
                 WHERE id = $1::uuid
                """,
                session_id,
                spec["query"],
                mode,
                json.dumps({
                    "target_name": spec.get("target_name") or "",
                    "engagement_title": spec.get("engagement_title") or title,
                    "seeded_from": "sample_workspace",
                }),
            )
        else:
            session_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO sessions (
                    id, firm_id, title, query, status, report_mode,
                    pipeline_state, created_by_user_id, metadata
                ) VALUES (
                    $1::uuid, $2::uuid, $3, $4, 'deliverable_ready', $5,
                    'deliverable_ready', $6::uuid, $7::jsonb
                )
                """,
                session_id, firm_id, title, spec["query"], mode,
                owner_id,
                json.dumps({
                    "target_name": spec.get("target_name") or "",
                    "engagement_title": spec.get("engagement_title") or title,
                    "seeded_from": "sample_workspace",
                }),
            )

        # Memberships — owner gets `lead`, others get `member`.
        if owner_id:
            await conn.execute(
                """
                INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
                VALUES ($1::uuid, $2::uuid, 'lead', $2::uuid)
                ON CONFLICT (engagement_id, user_id) DO UPDATE SET role = 'lead'
                """,
                session_id, owner_id,
            )
        for tid in team_ids:
            if tid == owner_id:
                continue
            await conn.execute(
                """
                INSERT INTO engagement_memberships (engagement_id, user_id, role, added_by)
                VALUES ($1::uuid, $2::uuid, 'contributor', $3::uuid)
                ON CONFLICT (engagement_id, user_id) DO NOTHING
                """,
                session_id, tid, owner_id or tid,
            )

        # Evidence objects + agent_outputs ↦ citations for the artifact
        # pipeline's _build_citations to find.
        await conn.execute(
            "DELETE FROM evidence_objects WHERE session_id = $1::uuid",
            session_id,
        )
        evidence_id_by_claim: dict[str, str] = {}
        for i, c in enumerate(citations):
            eid = str(uuid.uuid4())
            evidence_id_by_claim[c["claim_id"]] = eid
            await conn.execute(
                """
                INSERT INTO evidence_objects (
                    id, session_id, task_id, claim, quote, source_title,
                    source_type, confidence, is_inference, metadata
                ) VALUES (
                    $1::uuid, $2::uuid, $3, $4, $5, $6, $7,
                    'high', false, $8::jsonb
                )
                """,
                eid, session_id, i, c.get("text", "")[:200], c.get("text", ""),
                c.get("source_title", ""), c.get("source_type", "firm_library"),
                json.dumps({"claim_id": c["claim_id"]}),
            )

        # Analyst output (drives _build_citations).
        analyst_output = {
            "key_claims": [
                {
                    "claim_id": c["claim_id"],
                    "text": c.get("text", ""),
                    "evidence_ids": [evidence_id_by_claim[c["claim_id"]]],
                }
                for c in citations
            ],
            "recommendation": report["recommendation"],
        }
        await conn.execute(
            """
            INSERT INTO agent_outputs (session_id, agent_name, input, output)
            VALUES ($1::uuid, 'analyst_revision', '', $2)
            """,
            session_id, json.dumps(analyst_output),
        )

        # Report row.
        sources_json = report.get("sources") or []
        consulting_payload = report.get("consulting_payload") or {}
        await conn.execute(
            """
            INSERT INTO reports (
                session_id, recommendation, confidence_level, summary,
                key_reasons, risks, counterarguments, next_steps, sources,
                raw_output, caveats, evidence_bundle, verification,
                evidence_count, unsupported_claim_count,
                consulting_payload, reasoning_graph, claim_support
            ) VALUES (
                $1::uuid, $2, $3, $4,
                $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb,
                $10, $11, $12::jsonb, $13::jsonb,
                $14, $15,
                $16::jsonb, $17::jsonb, $18::jsonb
            )
            ON CONFLICT (session_id) DO UPDATE SET
                recommendation = EXCLUDED.recommendation,
                confidence_level = EXCLUDED.confidence_level,
                summary = EXCLUDED.summary,
                key_reasons = EXCLUDED.key_reasons,
                risks = EXCLUDED.risks,
                counterarguments = EXCLUDED.counterarguments,
                next_steps = EXCLUDED.next_steps,
                sources = EXCLUDED.sources,
                raw_output = EXCLUDED.raw_output,
                caveats = EXCLUDED.caveats,
                evidence_bundle = EXCLUDED.evidence_bundle,
                verification = EXCLUDED.verification,
                evidence_count = EXCLUDED.evidence_count,
                unsupported_claim_count = EXCLUDED.unsupported_claim_count,
                consulting_payload = EXCLUDED.consulting_payload,
                reasoning_graph = EXCLUDED.reasoning_graph,
                claim_support = EXCLUDED.claim_support,
                created_at = NOW()
            """,
            session_id,
            report["recommendation"],
            report.get("confidence_level", "Medium"),
            report["summary"],
            json.dumps(report.get("key_reasons", [])),
            json.dumps(report.get("risks", [])),
            json.dumps(report.get("counterarguments", [])),
            json.dumps(report.get("next_steps", [])),
            json.dumps(sources_json),
            json.dumps({"recommendation": report["recommendation"], "consulting_payload": consulting_payload}),
            report.get("caveats", ""),
            json.dumps([]),
            json.dumps({}),
            len(citations),
            0,
            json.dumps(consulting_payload),
            json.dumps({}),
            json.dumps([]),
        )

        # Section deepening rows (replace any prior rows for a clean
        # idempotent restore).
        await conn.execute(
            "DELETE FROM section_deepening_runs WHERE session_id = $1::uuid",
            session_id,
        )
        for d in deepenings:
            await conn.execute(
                """
                INSERT INTO section_deepening_runs (
                    session_id, firm_id, section_path, depth_directive,
                    triggered_by, original_section_json, deepened_section_json,
                    new_evidence_chunks_used, new_claim_ids, cost_usd,
                    wall_seconds, status, completed_at, accepted_at, accepted_by
                ) VALUES (
                    $1::uuid, $2::uuid, $3, $4,
                    $5::uuid, $6::jsonb, $7::jsonb,
                    $8, $9::jsonb, $10,
                    $11, $12, NOW(),
                    CASE WHEN $12 = 'accepted' THEN NOW() ELSE NULL END,
                    CASE WHEN $12 = 'accepted' THEN $5::uuid ELSE NULL END
                )
                """,
                session_id,
                firm_id,
                d["section_path"],
                d["directive"],
                owner_id,
                json.dumps({"note": "pre-deepening snapshot omitted in sample"}),
                json.dumps({"note": d.get("rationale", "")}),
                int(d.get("new_evidence_chunks_used", 0)),
                json.dumps(d.get("new_claim_ids", [])),
                float(d.get("cost_usd", 0.0)),
                float(d.get("wall_seconds", 0.0)),
                d.get("outcome", "completed"),
            )

    return {
        "session_id": session_id,
        "title": title,
        "mode": mode,
        "citations": len(citations),
        "deepenings": len(deepenings),
    }


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _weasyprint_available() -> bool:
    """Detect whether WeasyPrint's native runtime is installable here.
    Pillow + cairo + pango + gdk-pixbuf are required; Windows dev hosts
    typically lack them. We probe once and cache the answer.
    """
    try:
        from weasyprint import HTML  # type: ignore
        HTML(string="<html><body>x</body></html>").write_pdf()
        return True
    except Exception:
        return False


async def _generate_full_bundle(session_id: str) -> list[dict[str, Any]]:
    """Fire each artifact (type, format) target through the W10-W13
    export pipeline. Pure template render, $0 LLM cost.

    PDF formats are skipped when WeasyPrint's native runtime is
    unavailable (the seeder runs cleanly on Windows dev hosts; the
    Docker worker container has the libs and produces all 10).
    """
    from core.exports import GenerateArtifactRequest, generate_artifact

    has_weasyprint = _weasyprint_available()
    targets = [
        ("one_pager",       "html"),
        ("one_pager",       "pdf"),
        ("deck",            "pptx"),
        ("excel_model",     "xlsx"),
        ("email",           "md"),
        ("email",           "html"),
        ("email",           "pdf"),
        ("interview_guide", "md"),
        ("interview_guide", "html"),
        ("interview_guide", "pdf"),
    ]
    out: list[dict[str, Any]] = []
    for atype, fmt in targets:
        if fmt == "pdf" and not has_weasyprint:
            out.append({
                "artifact_type": atype, "format": fmt,
                "status": "skipped_no_weasyprint",
                "file_size_bytes": None,
                "failure_reason": "WeasyPrint native libs unavailable on this host",
            })
            continue
        req = GenerateArtifactRequest(
            session_id=uuid.UUID(session_id),
            artifact_type=atype,
            format=fmt,
        )
        try:
            result = await generate_artifact(req)
        except Exception as e:  # noqa: BLE001
            out.append({
                "artifact_type": atype, "format": fmt,
                "status": "exception",
                "error": str(e)[:200],
            })
            continue
        out.append({
            "artifact_type": atype, "format": fmt,
            "status": result.status,
            "file_size_bytes": result.file_size_bytes,
            "failure_reason": result.failure_reason,
        })
    return out


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


async def seed(
    *,
    reset: bool = False,
    skip_artifacts: bool = False,
) -> SeederSummary:
    """In-process seed function. Caller is responsible for the DB pool
    lifecycle — used by both the CLI wrapper (``main_async`` below)
    and by the test suite which manages its own pool.
    """
    workspace_spec = json.loads((_FIXTURES / _FIRM_FIXTURE).read_text(encoding="utf-8"))
    engagement_specs = [
        json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
        for name in _ENGAGEMENT_FIXTURES
    ]

    firm_id = await _ensure_firm(workspace_spec["firm"])
    print(f"firm: {workspace_spec['firm']['name']}  id={firm_id}")

    if reset:
        from db.connection import acquire
        async with acquire() as conn:
            # Reset every sample-workspace session for this firm to
            # force a clean restore. The DB CASCADE handles the
            # reports / evidence / agent_outputs / deepening
            # children, but artifact files on disk persist (those
            # are regenerated below).
            await conn.execute(
                "DELETE FROM sessions WHERE firm_id = $1::uuid",
                firm_id,
            )
            print("  reset: cleared sessions for this firm.")

    user_ids = await _ensure_users(firm_id, workspace_spec["users"])
    print(f"users: {len(user_ids)} provisioned")

    library_chunks = await _seed_library(firm_id)
    print(f"library: {library_chunks} new chunks ingested (existing rows dedup-skipped)")

    engagements: list[dict[str, Any]] = []
    artifacts_total = 0
    for spec in engagement_specs:
        print(f"engagement: restoring {spec['title']!r} ...")
        eng = await _restore_engagement(firm_id, user_ids, spec)
        if not skip_artifacts:
            bundle = await _generate_full_bundle(eng["session_id"])
            eng["artifacts"] = bundle
            ready = sum(1 for r in bundle if r["status"] == "ready")
            artifacts_total += ready
            print(f"  artifacts: {ready}/{len(bundle)} ready")
        engagements.append(eng)

    return SeederSummary(
        firm_id=firm_id,
        firm_slug=workspace_spec["firm"]["slug"],
        user_ids=user_ids,
        library_chunks=library_chunks,
        engagements=engagements,
        artifacts_generated=artifacts_total,
        used_cache=True,
    )


async def main_async(args: argparse.Namespace) -> SeederSummary:
    """CLI entry point — manages the DB pool around the seed call."""
    from db.connection import close_db, init_db

    await init_db()
    try:
        return await seed(
            reset=args.reset,
            skip_artifacts=args.skip_artifacts,
        )
    finally:
        await close_db()


def _print_summary(s: SeederSummary, workspace_spec: dict[str, Any]) -> None:
    print()
    print("=" * 72)
    print(f"Sample workspace ready — firm slug: {s.firm_slug}")
    print("=" * 72)
    print()
    print("Users (passwords: see fixtures/sample_workspace/workspace.json):")
    for u in workspace_spec["users"]:
        role = u.get("firm_role", "firm_member")
        print(f"  {role:<14}  {u['email']:<38}  {u['full_name']}")
    print()
    print(f"Library: {s.library_chunks} chunks added on this run.")
    print()
    print("Engagements:")
    for e in s.engagements:
        n_ready = sum(1 for a in (e.get("artifacts") or []) if a["status"] == "ready")
        total = len(e.get("artifacts") or [])
        print(f"  - {e['title']}")
        print(f"        mode={e['mode']}  session_id={e['session_id']}")
        print(f"        artifacts={n_ready}/{total} ready  deepenings={e['deepenings']}  citations={e['citations']}")
    print()
    print(f"Total artifacts generated: {s.artifacts_generated}")
    print()
    print("Manual smoke:")
    print(f"  1. Log in as {workspace_spec['users'][0]['email']!r}")
    print(f"     password: {workspace_spec['users'][0]['password']!r}")
    print("  2. Open either engagement in the workspace UI.")
    print("  3. Hit Export > Cover email (MD/HTML/PDF).")
    print()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true",
                   help="Drop and recreate sample-workspace sessions for this firm.")
    p.add_argument("--skip-artifacts", action="store_true",
                   help="Don't regenerate the artifact bundle (faster for partial reseeds).")
    args = p.parse_args()
    s = asyncio.run(main_async(args))
    workspace_spec = json.loads(
        (_FIXTURES / _FIRM_FIXTURE).read_text(encoding="utf-8"),
    )
    _print_summary(s, workspace_spec)


if __name__ == "__main__":
    main()
