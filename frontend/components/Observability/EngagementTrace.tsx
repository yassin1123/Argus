"use client";

import { useEffect, useState } from "react";

import {
  type EngagementTrace as EngagementTraceData,
  getEngagementTrace,
} from "@/lib/api/trace";

interface Props {
  /** Engagement / session id whose trace to render. */
  sessionId: string;
  /** Optional initial data so a server component or test can hydrate
   *  the view without a fetch. When supplied, the component skips
   *  the initial network call. */
  initialTrace?: EngagementTraceData | null;
  /** Optional run_id filter — pinned in the URL on a follow-up
   *  drill-in from /api/admin/traces/recent. */
  runId?: string;
}

/**
 * Observability panel — Phase 5 / Week 20 / Day 4. The "what
 * happened here" view an operator / firm-admin opens when an
 * engagement looks off.
 *
 * Sections:
 *   - Header: status, mode, total cost, wall time
 *   - Failure banner (only when status=failed) — stage + error + schema
 *   - Timeline: every stage with its duration
 *   - Per-stage rollup: cost + LLM-call count + error-count per agent
 *   - Verification verdict distribution
 *   - Retrieval breakdown by source
 *   - Gaps panel — flags which sections of the trace are missing data
 *
 * No prose content lives in this view. The trace API drops it at
 * assembly; the component just renders the shape it gets.
 */
export default function EngagementTrace({
  sessionId,
  initialTrace = null,
  runId,
}: Props) {
  const [trace, setTrace] = useState<EngagementTraceData | null>(initialTrace);
  const [loading, setLoading] = useState<boolean>(initialTrace === null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialTrace !== null) return;
    let cancelled = false;
    setLoading(true);
    getEngagementTrace(sessionId, { runId })
      .then((t) => {
        if (!cancelled) {
          setTrace(t);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(String(e?.message || e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, runId, initialTrace]);

  if (loading) {
    return (
      <div className="argus-trace argus-trace--loading" role="status">
        Loading trace…
      </div>
    );
  }
  if (error) {
    return (
      <div className="argus-trace argus-trace--error" role="alert">
        Failed to load trace: {error}
      </div>
    );
  }
  if (!trace) {
    return (
      <div className="argus-trace argus-trace--empty">
        No trace available for this engagement.
      </div>
    );
  }

  const totalUsd = trace.total_cost_usd ?? 0;
  const wallSec = trace.wall_ms ? trace.wall_ms / 1000 : null;
  const statusBadgeClass = `argus-trace__status argus-trace__status--${
    trace.status || "unknown"
  }`;

  return (
    <div className="argus-trace" data-testid="engagement-trace">
      {/* Header */}
      <div className="argus-trace__header">
        <div className="argus-trace__title">
          <span className={statusBadgeClass} data-testid="trace-status">
            {trace.status || "unknown"}
          </span>
          <span className="argus-trace__mode" data-testid="trace-mode">
            {trace.report_mode || "—"}
          </span>
          <span className="argus-trace__pipeline-state">
            {trace.pipeline_state || "—"}
          </span>
        </div>
        <div className="argus-trace__totals">
          <span data-testid="trace-total-cost">
            ${totalUsd.toFixed(4)} total
          </span>
          {wallSec !== null && (
            <span data-testid="trace-wall-time">
              {wallSec.toFixed(1)}s wall
            </span>
          )}
          <span data-testid="trace-call-count">
            {trace.llm_calls.length} LLM calls
          </span>
        </div>
      </div>

      {/* Failure banner */}
      {trace.failure.failed && (
        <div
          className="argus-trace__failure"
          role="alert"
          data-testid="trace-failure"
        >
          <div className="argus-trace__failure-title">
            Engagement failed
          </div>
          <dl className="argus-trace__failure-detail">
            <dt>Failed at stage</dt>
            <dd data-testid="trace-failed-stage">
              {trace.failure.failed_stage || "unknown"}
            </dd>
            {trace.failure.last_successful_stage && (
              <>
                <dt>Last successful stage</dt>
                <dd>{trace.failure.last_successful_stage}</dd>
              </>
            )}
            {trace.failure.error_message && (
              <>
                <dt>Error</dt>
                <dd>{trace.failure.error_message}</dd>
              </>
            )}
            {trace.failure.error_kind && (
              <>
                <dt>Error kind</dt>
                <dd>{trace.failure.error_kind}</dd>
              </>
            )}
            {trace.failure.writer_schema_failure?.field_path && (
              <>
                <dt>Schema field</dt>
                <dd>
                  {trace.failure.writer_schema_failure.schema_name}
                  {" · "}
                  {trace.failure.writer_schema_failure.field_path}
                </dd>
              </>
            )}
          </dl>
        </div>
      )}

      {/* Timeline */}
      <section className="argus-trace__section">
        <h3 className="argus-trace__heading">Timeline</h3>
        <ol className="argus-trace__timeline" data-testid="trace-timeline">
          {trace.timeline.map((s, i) => (
            <li
              key={`${s.stage}-${i}`}
              className={`argus-trace__timeline-row${s.ok ? "" : " argus-trace__timeline-row--fail"}`}
            >
              <span className="argus-trace__timeline-stage">{s.stage}</span>
              <span className="argus-trace__timeline-duration">
                {s.duration_ms === null ? "—" : `${(s.duration_ms / 1000).toFixed(1)}s`}
              </span>
              {s.detail && (
                <span className="argus-trace__timeline-detail">{s.detail}</span>
              )}
            </li>
          ))}
        </ol>
      </section>

      {/* Per-stage cost rollup */}
      <section className="argus-trace__section">
        <h3 className="argus-trace__heading">Cost by stage</h3>
        <table
          className="argus-trace__table"
          data-testid="trace-stage-rollups"
        >
          <thead>
            <tr>
              <th>Agent</th>
              <th>Calls</th>
              <th>Cost</th>
              <th>Tokens (prompt / completion)</th>
              <th>Errors</th>
            </tr>
          </thead>
          <tbody>
            {trace.stage_rollups.map((r) => (
              <tr key={r.agent}>
                <td>{r.agent}</td>
                <td>{r.call_count}</td>
                <td>${r.cost_usd.toFixed(4)}</td>
                <td>
                  {r.prompt_tokens.toLocaleString()} /{" "}
                  {r.completion_tokens.toLocaleString()}
                </td>
                <td>{r.error_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Verification verdict distribution */}
      <section className="argus-trace__section">
        <h3 className="argus-trace__heading">Verification</h3>
        <div
          className="argus-trace__verdicts"
          data-testid="trace-verdicts"
        >
          {trace.verification.assessments_total === 0 ? (
            <span className="argus-trace__empty">
              No verifier assessments recorded
            </span>
          ) : (
            <ul className="argus-trace__verdict-list">
              {Object.entries(trace.verification.verdict_distribution).map(
                ([outcome, n]) => (
                  <li
                    key={outcome}
                    className={`argus-trace__verdict argus-trace__verdict--${outcome}`}
                  >
                    <span>{outcome}</span>
                    <strong>{n}</strong>
                  </li>
                ),
              )}
            </ul>
          )}
        </div>
      </section>

      {/* Retrieval breakdown */}
      <section className="argus-trace__section">
        <h3 className="argus-trace__heading">Retrieval</h3>
        <div
          className="argus-trace__retrieval"
          data-testid="trace-retrieval"
        >
          <div>
            <strong>{trace.retrieval.evidence_count}</strong> evidence
            {" "}objects · {trace.retrieval.followup_query_count} follow-up
            queries
          </div>
          {Object.keys(trace.retrieval.evidence_by_source).length > 0 && (
            <ul className="argus-trace__retrieval-list">
              {Object.entries(trace.retrieval.evidence_by_source).map(
                ([src, n]) => (
                  <li key={src}>
                    {src}: <strong>{n}</strong>
                  </li>
                ),
              )}
            </ul>
          )}
        </div>
      </section>

      {/* Gaps panel — flags missing data so it's clear what we don't have */}
      {trace.gaps.length > 0 && (
        <section
          className="argus-trace__section argus-trace__section--gaps"
          data-testid="trace-gaps"
        >
          <h3 className="argus-trace__heading">Data gaps</h3>
          <ul>
            {trace.gaps.map((g) => (
              <li key={g} className="argus-trace__gap">
                {g.replace(/_/g, " ")}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
