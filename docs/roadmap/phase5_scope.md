# Phase 5 — Scope (Weeks 20–25)

**Status:** planning — Phase 4 closed 2026-05-24 (`phase-4-complete` tag).
**Phase 5 entry condition:** the collaboration layer (review,
discussion, ownership, notifications, version history) works
end-to-end as a coherent stack on a multi-user engagement. Met.

> Phase 5 is the operational + pilot phase. Phase 1 built the
> verification spine, Phase 3 built the deliverable suite, Phase 4
> built the team workflow. The product works. What it does not yet
> have is the operator shell, the enterprise hardening, and the
> real-firm validation needed to put it in a partner's hands. That
> is Phase 5. The v1.0 gate is one or more pilot firms shipping a
> client-ready Argus deliverable end-to-end.

## Four workstreams

### Quality (Weeks 20–21)

The eval harness has caught regressions through Phases 1–4 but the
NLI thresholds were tuned on the canonical 25-question set, not on
real-firm evidence. Phase 5 quality is closing the gap between
"passes the harness" and "lands cleanly on a partner's desk".

  - **NLI threshold tuning on real evidence.** Pull a calibration
    corpus from the Meridian-seeded engagements (+ any pilot
    firm content we land); recompute the LLM/DeBERTa/overlap
    weights against expert-labelled `supported|weak|contradicted`
    decisions; lock new thresholds behind a feature flag.
  - **Eval harness expansion.** Add the six-artifact regression
    (Phase 3) and the Phase 4 collaboration demo to the nightly
    schedule alongside the canonical question set. Surface
    failures as blocking deploys (existing pattern from Phase 1).
  - **Regression suites for the collaboration layer.** Today's
    Phase 4 demo is an integration smoke; convert the headline
    assertions into a pytest suite that runs against an
    ephemeral DB on every PR.
  - **Hallucination red-teaming.** Targeted attacks on the
    weakest points: claims that pass the NLI but contradict
    Pyramid coherence; section deepening that drifts away from
    the brief; cross-artifact verdict divergence (e.g. memo
    says "supported", deck cites the same claim as a placeholder).
    Each attack class becomes a regression case.

### Observability (Week 22)

The Phase 4 audit log is comprehensive but pure introspection.
Phase 5 observability is the operator-facing shell: who is using
the system, what is it spending, where is it slow, what is
breaking.

  - **Structured logging.** Replace ad-hoc `logger.info` calls
    with a typed event log (event_type + actor + session +
    payload); ship to the standard log aggregator.
  - **Metrics.** Per-endpoint p50/p95/p99, per-LLM-call cost +
    latency, per-engagement run time + token count, per-firm
    notification volume, per-user my-work-queue depth.
  - **Request tracing.** End-to-end trace from the API request
    through the writer pipeline through the verifier ensemble.
    Langfuse is already wired for LLM calls — extend with the
    surrounding request span so a slow engagement is debuggable
    in one trace.
  - **Cost dashboards.** Per-firm + per-engagement + per-job-type
    spend; hard ceiling enforcement (already shipped) made
    visible to operators; alert when a firm's daily spend
    crosses a configured threshold.
  - **Error monitoring.** Sentry-equivalent surface for
    unhandled exceptions + 5xx responses + verifier
    contradictions in production.

### Enterprise (Weeks 23–24)

Pilot firms will not put real client engagements through a system
that lacks SSO, data-retention controls, or a multi-instance
deploy story. Phase 5 enterprise is closing those gates.

  - **SSO.** Google Workspace + Microsoft Entra (the existing
    README claim, now made real). Per-firm IdP binding;
    just-in-time user provisioning on first sign-in; SAML +
    OIDC.
  - **Audit export.** CSV / JSONL export of `audit_events`
    scoped per firm + per engagement; signed-URL delivery for
    compliance pulls.
  - **Data retention + deletion.** Per-firm retention policy
    (default 7 years, configurable down to 90 days for trial
    firms); GDPR-style user-data deletion endpoint; verified
    cascade across `comments`, `notifications`, `audit_events`,
    `engagement_memberships`.
  - **Rate limiting.** Per-firm + per-user request budgets;
    abuse + runaway-loop protection; cost-cap-driven throttling.
  - **Multi-instance deploy.** Cross-node cache invalidation
    for `firm_modes`, artifact registry, notification
    preferences; session affinity for SSE / WebSocket-bound
    surfaces; the Phase 4 single-node assumption broken.
  - **Backup / restore.** Daily Postgres snapshot + the
    `export_artifacts` directory; documented restore drill;
    point-in-time-recovery target ≤ 1 hour.

### Pilots (Week 25)

The v1.0 gate. Everything above is in service of putting Argus
in a partner's hands and seeing the system survive contact with
a real engagement.

  - **Onboarding flow.** Firm creation wizard, first-user
    invite, mode-selection, brand asset upload, library seed
    upload. End-state: a firm partner can self-serve to a
    runnable first engagement in under 15 minutes.
  - **Real-firm fixtures.** Replace the Meridian sample
    workspace with the pilot firm's own brand + library + mode
    overrides. The seeded sample remains as the no-API-key
    evaluation entry point.
  - **Feedback instrumentation.** Wire the 60-second
    post-engagement form (already in the README) to a feedback
    table + a weekly digest to the Argus team.
  - **Pilot: Blackmont + EF.** The two named pilot firms.
    90-day terms (per the README): firm runs ≥3 real
    engagements; weekly working session; written testimonial
    if it lands. v1.0 ships when one of them signs off on a
    real client deliverable end-to-end.

## Phase 5 carry-forwards from Phase 4

See [docs/eval/phase4_close.md](../eval/phase4_close.md) for the
full carry-forward list. The Phase 5 weeks above absorb them:

  - W19/D3 version-history React surface → folds into Week 20
    quality polish (the diff component already shape-matches
    the backend; it's UI plumbing).
  - Production SMTP wiring → Week 23 enterprise.
  - Notification digest batching + WebSocket push → Week 22
    observability (digest) + Week 23 enterprise (push channel).
  - Companies House TIFF/OCR → Week 20–21 quality.
  - Multi-instance cache invalidation → Week 23–24 enterprise.
  - Text-range live re-anchoring + element-level artifact
    commenting → defer; not pilot-blocking.
  - WeasyPrint deploy story → Week 24 enterprise (Docker is
    fine today; the pilot deploy needs a documented host
    requirement).

## Out of scope for Phase 5

Phase 5 is operations + pilots, not new product surface area. The
following are explicitly deferred:

  - Bloomberg / FactSet / Refinitiv connectors (Phase 6).
  - Mobile review experience (Phase 6).
  - Multi-language deliverable templates (Phase 6).
  - Public sample workspace for prospective firms — useful for
    sales, but not a v1.0 gate.

## Done condition for Phase 5

Phase 5 closes when:

  - The Phase 4 collaboration demo plus the Phase 3 six-artifact
    regression both run on nightly CI and block deploys on
    failure.
  - SSO is live for at least one pilot firm.
  - The cost + latency + error dashboards are operator-readable
    and on-call has a runbook.
  - At least one pilot firm has shipped a client-ready Argus
    deliverable to a real client and signed off in writing
    that it landed.

That last bullet is the v1.0 gate.
