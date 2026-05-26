# Week 20 — Observability foundation

**Status:** ship
**Closed:** 2026-05-26
**Branch:** `phase-5/week-20` — D1, D2, D3, D4, D5 committed.

> Week 20 opens Phase 5 with the observability layer the pilots
> need to be survivable. Structured correlated logging
> (privacy-redacted), counters + histograms backed by a metrics
> table, a cost ledger with per-engagement and per-firm rollups
> reconciled to the ceiling helper, per-engagement trace
> reconstruction with failure diagnosis, and an admin health
> dashboard that joins it all into one screen. When a real firm
> hits a problem, it's now diagnosable.

## Component check

| Component | Status | Evidence |
|---|---|---|
| Structured logging + traces + redaction (D1) | ✅ | 6 tests; `core/observability/{logging,trace,middleware}.py`; manual smoke proved a planted prose secret never lands in the log envelope |
| Metrics collection + query API + Prometheus seam (D2) | ✅ | 7 tests; `core/observability/metrics.py` + `api/metrics.py`; firm-scoping enforced server-side |
| Cost ledger + rollups + ceiling reconciliation (D3) | ✅ | 7 tests; `core/observability/{cost,cost_rollups}.py` + `api/cost.py`; `session_cost_total` is the canonical "how much has this engagement cost" |
| Request tracing + lifecycle view + failure diagnosis (D4) | ✅ | 7 backend tests + 4 frontend tests; `core/observability/trace_view.py` + `api/trace.py` + `frontend/components/Observability/EngagementTrace.tsx` |
| Admin dashboard + observability e2e (D5) | ✅ | 5 frontend tests; `api/observability_dashboard.py` + `frontend/components/Observability/AdminDashboard.tsx`; e2e passes 11/11 headline assertions |

**Backend test totals:** 27 W20 tests across D1–D4 (6 + 7 + 7 + 7). **Frontend:** 9 tests across D4–D5 (4 + 5). **E2E:** 11/11 headline assertions.

## End-to-end demo

Ran [tools/run_week20_observability_e2e.py](../../tools/run_week20_observability_e2e.py)
against a five-engagement simulated workload — three M&A + one
growth_strategy on firm A, one M&A on firm B (firm-scoping
control), one forced failure (writer schema validation) on firm
A. Cost discipline: zero real LLM spend (the runner uses the
same in-memory DB fake the per-day tests use; token counts +
USD values are derived from the W7/W8 eval-run history so the
shape matches a real workload).

**Headline numbers from the run:**

  - **Engagements:** 5 total — 4 complete, 1 failed
  - **Total cost across the workload:** **$2.03**
  - **Cost ledger sums match per-engagement totals:** every
    engagement's `session_cost_total` matched its reported
    LLM-call total to within $0.0001
  - **Metrics reflect the workload:** 5 `engagement.started`
    counters (4 m_and_a, 1 growth_strategy), 31 `llm.call`
    counters (18 anthropic, 13 openai), verifier verdict
    distribution `{supported_high: 72, supported_low: 24,
    weak: 8, contradicted: 4}` across the 4 completed runs
  - **Failure diagnosed:** the failed engagement's trace shows
    `failed_stage=research_gathered`,
    `last_successful_stage=research_gathered`, `error_kind=
    schema_validation_failed`, `error_message="WriterSchema
    ValidationError: missing required field
    valuation_range.method"`, `writer_schema_failure={schema_name,
    field_path}` only (no `raw_text_excerpt` leak), `total_cost_
    usd=$0.2275` burned before failure
  - **Privacy audit:** a planted prose secret
    ("CONFIDENTIAL: target Q2 EBITDA dropped 18% YoY per the
    leaked filing extract…") passed into log lines via banned
    field names + into the failed engagement's
    `writer_schema_failure.raw_text_excerpt` was **absent from
    every observability surface** — logs, metrics, cost ledger,
    traces. The `[REDACTED]` sentinel is present where the leak
    was attempted, so the redaction is visibly loud
  - **Firm scoping:** firm-A ledger total $1.58 (matches the
    four firm-A engagements' costs); firm-B ledger total $0.45
    (matches firm-B's single engagement); firm-A's
    `recent_traces` does **not** contain firm-B's session_ids

## The verification-distribution finding (Week 21 starting point)

The dashboard's verification panel computed the supported / partial /
insufficient breakdown from the verifier verdict counter:

  - **88.9% supported** (96 of 108 assessments — supported_high + supported_low)
  - **7.4% partial** (8 weak)
  - **3.7% insufficient** (4 contradicted)

That looks healthy in isolation, but it's the eval-run histogram —
the real-firm rates will land different once Phase 5 Week 21 tunes
the NLI thresholds on real-firm evidence corpora. The signal the
dashboard surfaces is the right shape; the *numbers* are the W21
calibration problem, not a W20 blocker. **This is exactly the
quality signal the W20/D5 spec asked the dashboard to expose so
W21 has a starting point.** Not a finding to act on this week — a
finding to carry into next week's threshold-tuning work.

## What works

  - One `grep trace_id=<id>` on the log file reconstructs the full
    engagement lifecycle. The W20/D1 contextvars propagation
    survived every async boundary in the orchestrator — no
    additional plumbing per call site was needed.
  - The cost ledger is one schema with three rollup shapes
    (`session_cost_total` → ceiling source-of-truth,
    `engagement_cost` → workspace panel, `firm_cost` → admin
    dashboard, `cost_by_model` → system view). No drift between
    them — they all SUM the same column.
  - Failed-engagement diagnosis works on the *minimum* metadata
    we already record. We didn't need a separate failure table:
    the existing `sessions.metadata.pipeline_trace` + the W7/D5
    `writer_schema_failure` persistence + the W20/D1 structured
    `pipeline.failed` event together reconstruct everything an
    operator needs to triage.
  - The privacy redaction discipline is testable. The denylist +
    suffix rule + `[REDACTED]` sentinel make leaks **visible**
    (the sentinel shows where prose was attempted) rather than
    silent.
  - Firm-scoping is a single helper (`_scope_firm_id` / its trace
    + cost equivalents) that every admin endpoint reuses. The
    same gate protects the metrics API, the cost API, the trace
    API, and the dashboard API — one rule, four surfaces.

## What's still open

  - **External log + metrics sinks.** The shipping seams are in
    place (`configure_event_logging(extra_handlers=...)` + the
    Prometheus exposition endpoint) but no Datadog/ELK/Loki/Grafana
    is wired today. That's a deploy decision per pilot firm, not
    a Phase 5 product gate.
  - **Alerting.** No "error rate spiked past threshold" hook
    yet. Phase 5 W22 polish or post-pilot.
  - **Long-term metrics retention + rollup tables.** Raw
    `metric_events` rows are fine at pilot scale (low hundreds
    of engagements/day). Once volume grows, daily rollups +
    archival to cold storage. Not blocking today.
  - **Trace assembly performance on the recent-failures view.**
    Today the dashboard's `recent_failures` panel calls
    `recent_traces` which queries `sessions` + joins
    `cost_ledger` per row. At ~10–50 rows it's fine; beyond a
    few hundred a materialised view (or just a separate
    `engagement_summary` write-on-completion table) is needed.
    Flagged as the first scale carry; not a pilot blocker.
  - **W19/D3 version-history React surface.** Inherited from the
    Phase 4 close — backend shipped, UI deferred into Phase 5
    quality polish.
  - **Real-firm verification rates.** The 88.9% supported rate
    above is the eval set, not real evidence. Week 21 NLI
    threshold tuning on real-firm corpora is where that number
    becomes calibratable.

## Ship decision

**Ship.** Every hard rule the spec laid down is held by tests +
the e2e:

  - **No prose content** in any observability surface — tested
    explicitly with a planted secret across logs, metrics, cost
    ledger, and traces
  - **Firm scoping** holds — both the route-handler gates and
    the e2e cross-firm assertion confirm it
  - **Failed engagement is diagnosable** — the e2e's failed
    engagement produces a trace with stage + reason + cost-burned
    + schema-field, all from data we already record
  - **Budget:** zero real LLM spend on the e2e (cost-cap rule
    honoured)

## Phase 5 / Week 21 starts with

  - The verification-distribution signal the dashboard surfaces —
    a real measurement, not a guess
  - The metrics + cost ledger + trace surfaces in place so
    Week 21's threshold-tuning work has live signal feedback
    (every NLI threshold change shows up as a verdict
    redistribution on the dashboard within seconds)
  - The seam for a separate eval-suite metric stream (`extra_handlers`
    on the event logger) so W21's expanded eval harness can
    ship its results to the same dashboard

## Retro

**What went well.** The four W20 components composed cleanly
because each one read from the layer below without coupling to
its internals. Day 4's trace assembler joined four data sources
(sessions metadata + llm_calls + metric_events + payload_versions)
without any of them needing a schema change — the trace_id
contextvar from D1 was sufficient correlation. The cost ledger
ceiling reconciliation (D3) was the single-cleanest piece: one
function `session_cost_total` replaced what would have been a
separate accumulator per call site.

**What was tricky.** The `metric_events` JSONB query path — the
group-by-label SQL has to parameterise the JSON path string to
avoid concat injection, and the test fake had to mirror the
exact arg-ordering the SQL builder used. Spent a bounded amount
of time on that; tests caught two iterations of arg-ordering
drift before the e2e ran.

**What to carry into Week 21.** The redaction-with-sentinel
discipline is the right shape for the eval expansion work — when
W21 starts sending sample inputs through the harness, the same
denylist + suffix rule + sentinel pattern keeps the eval logs
safe for sharing externally without leaking firm content.
