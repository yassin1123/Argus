"use client";

// Live-pilot watch view — Phase 5 / Week 25 / Day 2.
// The operator's active-pilot screen. Short-polls the live-pilot endpoint
// so a problem surfaces in seconds: firing alerts up top, in-flight
// engagements + their stage + cost, live cost burn, verification mix,
// and feedback as it arrives.

import { useCallback, useEffect, useRef, useState } from "react";

import { getLivePilot, type LivePilotView as LivePilotData } from "@/lib/api/livePilot";

const DEFAULT_POLL_MS = 15000;

export default function LivePilotView({
  firmId,
  pollMs = DEFAULT_POLL_MS,
}: {
  firmId?: string;
  pollMs?: number;
}) {
  const [data, setData] = useState<LivePilotData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastTick, setLastTick] = useState<string>("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const d = await getLivePilot({ firmId });
      setData(d);
      setError(null);
      setLastTick(new Date().toLocaleTimeString());
    } catch (e) {
      setError((e as Error).message);
    }
  }, [firmId]);

  useEffect(() => {
    void refresh();
    timer.current = setInterval(() => void refresh(), pollMs);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh, pollMs]);

  if (error) return <p className="text-sm text-red-700">Live pilot: {error}</p>;
  if (!data) return <p className="text-sm text-argus-secondary">Loading live pilot…</p>;

  const vd = data.verification_distribution;
  const cb = data.cost_burn;

  return (
    <div className="space-y-4" data-testid="live-pilot">
      <header className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-argus-primary">
          Live pilot {data.has_critical ? "🔴" : data.alert_count ? "🟠" : "🟢"}
        </h2>
        <span className="text-[11px] text-argus-secondary">
          last {lastTick || "—"} · {data.window_minutes}m window · auto-refresh
        </span>
      </header>

      {/* Alerts first — the whole point is catching a problem fast. */}
      {data.alerts.length > 0 ? (
        <div className="space-y-1" data-testid="live-pilot-alerts">
          {data.alerts.map((a, i) => (
            <div
              key={`${a.kind}-${i}`}
              className={`rounded-argus px-3 py-2 text-sm ${
                a.severity === "critical"
                  ? "bg-red-50 text-red-800"
                  : "bg-amber-50 text-amber-800"
              }`}
            >
              {a.severity === "critical" ? "⛔" : "⚠️"} <strong>{a.kind}</strong> — {a.detail}
            </div>
          ))}
        </div>
      ) : (
        <p className="rounded-argus bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          No alerts firing.
        </p>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="In-flight" value={`${data.active_engagements.filter((e) => e.active).length}`} />
        <Kpi label="Today spend" value={`$${cb.today_usd.toFixed(2)}`} sub={`MTD $${cb.month_to_date_usd.toFixed(2)}`} />
        <Kpi
          label="Budget used"
          value={cb.used_pct != null ? `${cb.used_pct.toFixed(0)}%` : "—"}
          sub={cb.blocks_new_engagements ? "soft-stop active" : ""}
        />
        <Kpi label="Verif. insufficient" value={`${vd.insufficient_pct.toFixed(0)}%`} sub={`${vd.total} claims`} />
      </div>

      {/* Active engagements */}
      <section>
        <p className="mb-1 text-xs font-medium text-argus-secondary">Engagements (last 2h)</p>
        {data.active_engagements.length === 0 ? (
          <p className="text-sm text-argus-secondary">None.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase text-argus-tertiary">
                <th className="py-1">Title</th>
                <th>Status</th>
                <th>Stage</th>
                <th className="text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.active_engagements.map((e) => (
                <tr key={e.session_id} className="border-t border-argus-border-subtle">
                  <td className="py-1 text-argus-primary">{e.title}</td>
                  <td className={e.active ? "text-argus-accent" : "text-argus-secondary"}>
                    {e.active ? "● running" : e.status}
                  </td>
                  <td className="text-argus-secondary">{e.pipeline_state || "—"}</td>
                  <td className="text-right tabular-nums">${e.cost_usd.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Recent feedback */}
      {(data.feedback.recent_claim_feedback.length > 0 ||
        data.feedback.recent_artifact_ratings.length > 0) && (
        <section className="text-xs text-argus-secondary">
          <p className="mb-1 font-medium">Recent feedback</p>
          {data.feedback.recent_claim_feedback.slice(0, 5).map((c, i) => (
            <div key={`cf-${i}`}>claim: {c.assessment}</div>
          ))}
          {data.feedback.recent_artifact_ratings.slice(0, 5).map((r, i) => (
            <div key={`ar-${i}`}>
              {r.artifact_type || "artifact"}: {r.rating}★
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-argus border border-argus-border-subtle p-3">
      <p className="text-[11px] uppercase tracking-wide text-argus-secondary">{label}</p>
      <p className="mt-1 text-lg font-semibold text-argus-primary">{value}</p>
      {sub ? <p className="text-[11px] text-argus-secondary">{sub}</p> : null}
    </div>
  );
}
