# Day-One Notes — Deploying Argus at a Real Client

This document is the bridge between the portfolio demo and a real engagement. The repo as-shipped optimizes for *evaluating the system in 2 minutes*, not for running it in a regulated environment. These are the things I'd add — and the order I'd add them in — on day one of an actual deployment.

The point isn't to enumerate every enterprise feature. It's to show that the architecture was designed with the path to those features in mind, not as bolt-ons.

---

## Where the architecture already does the right thing

Before adding anything: the choices that already hold up under scrutiny.

| Decision | Why it survives day one |
|----------|--------------------------|
| Async pipeline behind Celery + Redis | Long-running LLM jobs don't block the API. Easy horizontal scale on the worker pool. |
| `claim_support_rows` joining claims ↔ evidence ↔ verifier verdicts | The audit trail of *which evidence supports which claim with which verdict* is already in the schema, not glued on later. |
| Presentation DTOs server-side ([backend/models/workspace_dto.py](../backend/models/workspace_dto.py)) | The trust rail's "8 of 9 supported" isn't computed in the browser — it's computed once, server-side, and shipped pre-formatted. Auditable, cacheable, swappable. |
| pgvector embeddings + claim ids + evidence UUIDs | Each layer has a stable id you can foreign-key against. Lineage works. |
| Strict mode flags (`ARGUS_STRICT_NO_INFERENCE_ONLY`, `ARGUS_STRICT_WRITER_CLAIM_IDS`) | The pipeline can be tightened *for one client* without forking the codebase. |
| Deterministic demo mode + fixtures shared with tests | Same data drives evaluation, regression tests, and the case study. Drift is impossible. |

---

## Day 1 — make it safe to put a client in front of

**Multi-tenancy + auth.** Right now `sessions` belongs to nobody. Add a `tenant_id` (uuid) to every table that holds client data (sessions, evidence_objects, agent_outputs, claim_support_rows, embeddings, uploaded_files, conversation_turns). Add a `created_by_user_id` for actor attribution. Mount auth in front of every route via FastAPI dependency — accept either a JWT (for SSO via Auth0/Okta) or an HMAC-signed service token (for ingress from a client's existing tools). Reject any DB query that doesn't carry an active `tenant_id`.

**Per-tenant model quotas.** The model router ([backend/core/model_router.py](../backend/core/model_router.py)) is already the choke-point — extend it to read tenant-scoped budget caps and refuse to issue a completion that would exceed the day's spend cap. Cheaper than reactive rate-limiting and the failure mode is graceful: pipeline pauses with a "quota reached" event, doesn't crash.

**Audit log.** New table `audit_events` (tenant_id, actor, action, resource_type, resource_id, payload, ts). Every API call, every export, every pipeline run, every chat message. Immutable, append-only, with a 90-day hot retention and S3 cold archive. This is the table the client's compliance team will ask to see — not the application logs.

**Secrets via the platform secret manager.** `.env` files are fine for the demo, fragile in production. Move all keys to AWS Secrets Manager (or the client's vault — many enterprise clients require BYO). Mount via IRSA on EKS or instance profile on EC2. Rotate quarterly with a one-line config change.

---

## Day 1–7 — make it observable and provable

**Tracing.** Wrap every agent call with OpenTelemetry spans (`agent.planner`, `agent.researcher.web_query`, `agent.verifier.claim_check`). Pipe to Honeycomb or Datadog. Single dashboard answering: *what's slow today, what's failing today, what changed in the last 24h.* The pipeline already emits `pipeline_events` rows — those become OpenTelemetry events for free if you swap the writer.

**Per-stage SLOs.** Planner < 10s p95. Researcher < 60s p95. Verifier < 15s p95. Page out on breach. The fixture data shows what "normal" looks like (planner 4.3s, researcher 38.7s, verifier 7.1s) — those are the seed values for SLO definitions.

**Eval set + regression gate.** Promote the Germany-vs-France fixture to the first row of an eval set. Add 5 more strategic questions with curated evidence and gold-standard recommendations. CI runs the live pipeline against each on every merge to main. Any regression on `verifier.supported_count` or `claim_support.entailment_score` fails the build. This is what stops "fixed it for one client, broke it for another."

**Per-claim evidence drill-down in the UI is the demo to lead with.** It's the single thing a compliance officer actually wants to click on. The evidence drawer ([frontend/components/Report/EvidenceDrawer.tsx](../frontend/components/Report/EvidenceDrawer.tsx)) already exists; in production, add a "copy citation" button that emits the source URL + retrieval timestamp + content hash. Clients put those into their own systems.

---

## Day 7–30 — productionize the long tail

**Document ingest at scale.** Today's chunker is fine for 10 PDFs, painful for 10,000. Add a queue-based ingest worker, idempotent on `(tenant_id, file_hash)`. Move embeddings to a managed pgvector cluster (Aurora pgvector or AlloyDB). Add a "reindex" admin operation for prompt changes that need fresh embeddings.

**Cost transparency per session.** The pipeline already records `token_count` per `agent_outputs`. Roll that into a per-session cost breakdown surfaced in the trust rail (already drafted for the live SSE counter — just persist the final). Clients will ask *"how much did this report cost to produce"* by week two.

**Data residency.** EU clients want EU-only inference. Add a `region` column to `tenants`. Route inference through region-pinned Anthropic / OpenAI endpoints (AWS Bedrock has been the cleanest path here). The model_router already abstracts the choice — extend it to consult tenant region.

**Export integrity.** PDFs are the deliverable; clients forward them. Add a content-hash watermark page on every export with a verifier URL: *"this report's evidence ledger is auditable at argus.example.com/v/<hash>"*. Hash includes tenant_id, session_id, and a sha256 of the report payload. If the client edits the PDF, the hash mismatches.

**Slack/Teams + ticketing handoff.** Forward-deployed AI doesn't end at the report — it integrates with the workflow. Add a "send to Slack" action that posts the recommendation + a single deep-link to the workspace. For longer engagements, a Linear/Jira plug-in that turns `next_steps` into tickets with the source claim attached.

---

## What I'd deliberately defer

A short "what I'm *not* building yet" list is more credible than a long roadmap.

- **Real-time collaboration** on workspaces. Useful, expensive, can be replaced for now by clean export + a comment thread on the deliverable side.
- **Custom-branded white-label UI.** The trust rail and evidence framing *are* the product. Putting a customer logo at the top is theater; keep the chrome neutral.
- **More LLM providers.** Until cost or latency forces it, OpenAI for analysis + Cohere for rerank is the pareto frontier. Adding Anthropic / Mistral doubles the prompt-eval surface.
- **Auto-publishing reports.** A human signs off before send. The trust rail's caveat banner is a *suggestion to review*, not a block — but in production the caveats banner becomes a hard block on the export action until acknowledged.

---

## What this maps to as a job

A real engagement looks like *"the architecture above, plus tenancy plus auth plus an eval set plus tracing plus a deploy pipeline,"* delivered in 2–3 weeks per increment with the client's compliance team in the room. The repo demonstrates the AI architecture and the deliverable framing; the production work is the four bullets above the line "make it safe to put a client in front of." That's the work, and that's the order.

The reason the demo is worth showing is not that it's deployable — it's that the layers that need to be added are already shaped for it. Adding `tenant_id` to a schema that already has `claim_support_rows` joining audit-grade evidence is a one-day migration. Adding it to a schema that *doesn't* have that backbone is a six-week refactor.
