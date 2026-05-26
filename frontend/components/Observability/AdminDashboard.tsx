"use client";

import { useEffect, useState } from "react";

import {
  type DashboardData,
  getDashboard,
} from "@/lib/api/observability";

interface Props {
  /** Window to scope the dashboard to. Default 24h. */
  hours?: number;
  /** System-admin only — restrict to one firm. */
  firmId?: string;
  /** Optional initial data for server-render / tests. When supplied,
   *  the component skips the initial fetch. */
  initialData?: DashboardData | null;
}

/**
 * Admin observability dashboard — Phase 5 / Week 20 / Day 5.
 *
 * One-screen system-health view. Reads:
 *   - volume (engagements started / completed / failed / in-flight)
 *   - success rate
 *   - cost (firm rollup for firm-admins; system view for sys-admins)
 *   - verification verdict distribution (the quality signal Week 21
 *     uses as its starting point)
 *   - recent failures (clickable to drill into W20/D4 EngagementTrace)
 *
 * Firm-scoping happens server-side (the backend forces firm-admins
 * to their own firm regardless of any ``?firm_id`` query param);
 * the component just renders what it gets.
 */
export default function AdminDashboard({
  hours = 24,
  firmId,
  initialData = null,
}: Props) {
  const [data, setData] = useState<DashboardData | null>(initialData);
  const [loading, setLoading] = useState<boolean>(initialData === null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialData !== null) return;
    let cancelled = false;
    setLoading(true);
    getDashboard({ hours, firmId })
      .then((d) => {
        if (!cancelled) {
          setData(d);
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
  }, [hours, firmId, initialData]);

  if (loading) {
    return (
      <div className="argus-dashboard argus-dashboard--loading" role="status">
        Loading observability…
      </div>
    );
  }
  if (error) {
    return (
      <div className="argus-dashboard argus-dashboard--error" role="alert">
        Failed to load dashboard: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="argus-dashboard argus-dashboard--empty">
        No dashboard data.
      </div>
    );
  }

  const v = data.volume;
  const vd = data.verification;
  const cost = data.cost;

  return (
    <div className="argus-dashboard" data-testid="admin-dashboard">
      <header className="argus-dashboard__header">
        <h2>System health — last {data.hours}h</h2>
        <div className="argus-dashboard__scope">
          {cost.scope === "system"
            ? "Scope: all firms (system-admin)"
            : `Scope: firm ${data.firm_scoped_to?.slice(0, 8) || "—"}…`}
        </div>
      </header>

      {/* Top-line KPIs */}
      <section className="argus-dashboard__kpis">
        <div className="argus-dashboard__kpi" data-testid="kpi-started">
          <span className="argus-dashboard__kpi-label">Engagements started</span>
          <strong>{v.started}</strong>
        </div>
        <div className="argus-dashboard__kpi" data-testid="kpi-completed">
          <span className="argus-dashboard__kpi-label">Completed</span>
          <strong>{v.completed}</strong>
        </div>
        <div className="argus-dashboard__kpi" data-testid="kpi-failed">
          <span className="argus-dashboard__kpi-label">Failed</span>
          <strong className="argus-dashboard__kpi--alert">{v.failed}</strong>
        </div>
        <div className="argus-dashboard__kpi" data-testid="kpi-in-flight">
          <span className="argus-dashboard__kpi-label">In flight</span>
          <strong>{v.in_flight}</strong>
        </div>
        <div className="argus-dashboard__kpi" data-testid="kpi-success-rate">
          <span className="argus-dashboard__kpi-label">Success rate</span>
          <strong>{v.success_rate_pct.toFixed(1)}%</strong>
        </div>
        <div className="argus-dashboard__kpi" data-testid="kpi-artifacts">
          <span className="argus-dashboard__kpi-label">Artifacts generated</span>
          <strong>{data.artifacts_generated}</strong>
        </div>
        <div className="argus-dashboard__kpi" data-testid="kpi-total-cost">
          <span className="argus-dashboard__kpi-label">Total cost</span>
          <strong>${cost.total_usd.toFixed(4)}</strong>
        </div>
      </section>

      {/* Volume by mode */}
      <section className="argus-dashboard__section">
        <h3>Engagements by mode</h3>
        {Object.keys(v.by_mode).length === 0 ? (
          <div className="argus-dashboard__empty">No engagements in window.</div>
        ) : (
          <table className="argus-dashboard__table" data-testid="volume-by-mode">
            <thead>
              <tr>
                <th>Mode</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(v.by_mode).map(([mode, info]) => (
                <tr key={mode}>
                  <td>{mode}</td>
                  <td>{info.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Cost by model */}
      <section className="argus-dashboard__section">
        <h3>Cost by model</h3>
        {cost.by_model.length === 0 ? (
          <div className="argus-dashboard__empty">No cost rows in window.</div>
        ) : (
          <table className="argus-dashboard__table" data-testid="cost-by-model">
            <thead>
              <tr>
                <th>Model</th>
                <th>Provider</th>
                <th>Calls</th>
                <th>Cost</th>
              </tr>
            </thead>
            <tbody>
              {cost.by_model.map((r) => {
                const label = r.model || r.label || "—";
                const calls = r.call_count ?? r.count ?? 0;
                const usd = r.total_usd ?? r.cost_usd ?? 0;
                return (
                  <tr key={label}>
                    <td>{label}</td>
                    <td>{r.provider || "—"}</td>
                    <td>{calls}</td>
                    <td>${usd.toFixed(4)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {/* Verification (the W21 quality signal) */}
      <section className="argus-dashboard__section">
        <h3>Verification verdict distribution</h3>
        <div
          className="argus-dashboard__verification"
          data-testid="verification-block"
        >
          <div>
            <span className="argus-dashboard__verdict argus-dashboard__verdict--supported">
              {vd.supported_pct.toFixed(1)}% supported
            </span>
            <span className="argus-dashboard__verdict argus-dashboard__verdict--partial">
              {vd.partial_pct.toFixed(1)}% partial
            </span>
            <span className="argus-dashboard__verdict argus-dashboard__verdict--insufficient">
              {vd.insufficient_pct.toFixed(1)}% insufficient
            </span>
          </div>
          {vd.total === 0 ? (
            <div className="argus-dashboard__empty">
              No verifier assessments recorded.
            </div>
          ) : (
            <table className="argus-dashboard__table">
              <thead>
                <tr>
                  <th>Verdict</th>
                  <th>Count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(vd.verdicts).map(([k, n]) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td>{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {/* Recent failures */}
      <section className="argus-dashboard__section">
        <h3>Recent failures</h3>
        {data.recent_failures.length === 0 ? (
          <div className="argus-dashboard__empty" data-testid="no-failures">
            No failures in window. ✅
          </div>
        ) : (
          <ul
            className="argus-dashboard__failures"
            data-testid="recent-failures"
          >
            {data.recent_failures.map((f) => (
              <li key={f.session_id} className="argus-dashboard__failure-row">
                <a
                  href={`/admin/traces/${f.session_id}`}
                  className="argus-dashboard__failure-link"
                >
                  {f.session_id.slice(0, 8)}…
                </a>
                <span>{f.report_mode || "—"}</span>
                <span>at {f.failed_stage || "unknown stage"}</span>
                <span>${f.total_cost_usd.toFixed(4)} burned</span>
                {f.error_message && (
                  <span className="argus-dashboard__failure-error">
                    {f.error_message.slice(0, 80)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
