"use client";

// Pilot-health panel — Phase 5 / Week 24 / Day 3.
// The operator's daily-driver view during the pilot. Renders the
// firm-scoped aggregates: claim-feedback distribution, average artifact
// rating, average edit rate, and the weekly check-in trend. Accepts the
// `pilot_health` block straight off the W20 dashboard response, or
// fetches standalone via getPilotHealth.

import { useEffect, useState } from "react";

import { getPilotHealth, type PilotHealth } from "@/lib/api/pilotFeedback";

export default function PilotHealthPanel({
  data: initial = null,
  firmId,
}: {
  data?: PilotHealth | null;
  firmId?: string;
}) {
  const [data, setData] = useState<PilotHealth | null>(initial);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initial !== null) return;
    let cancelled = false;
    getPilotHealth(firmId)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [initial, firmId]);

  if (error) return <p className="text-sm text-red-700">Pilot health: {error}</p>;
  if (!data) return <p className="text-sm text-argus-secondary">Loading pilot health…</p>;

  const cf = data.claim_feedback;
  const ar = data.artifact_ratings;
  const er = data.edit_rate;

  return (
    <section className="rounded-argus border border-argus-border-subtle bg-surface p-4">
      <h3 className="text-sm font-semibold text-argus-primary">Pilot health</h3>

      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Claim feedback" value={`${cf.total}`} sub={`${cf.pct.correct}% correct`} />
        <Kpi
          label="Avg artifact rating"
          value={ar.rating_count ? `${ar.average_rating}★` : "—"}
          sub={`${ar.rating_count} rated`}
        />
        <Kpi
          label="Avg edit rate"
          value={er.engagement_count ? `${er.average_edit_pct}%` : "—"}
          sub={`${er.engagement_count} approved`}
        />
        <Kpi label="Check-ins" value={`${data.checkin_trend.length}`} sub="weeks logged" />
      </div>

      {cf.total > 0 && (
        <div className="mt-4">
          <p className="mb-1 text-xs font-medium text-argus-secondary">
            Verification feedback distribution
          </p>
          <div className="flex h-3 w-full overflow-hidden rounded-full">
            <Bar pct={cf.pct.correct} className="bg-emerald-500" title={`correct ${cf.pct.correct}%`} />
            <Bar pct={cf.pct.wrong_supported} className="bg-red-600" title={`wrong-supported ${cf.pct.wrong_supported}%`} />
            <Bar pct={cf.pct.wrong_flagged} className="bg-amber-500" title={`wrong-flagged ${cf.pct.wrong_flagged}%`} />
            <Bar pct={cf.pct.unsure} className="bg-gray-400" title={`unsure ${cf.pct.unsure}%`} />
          </div>
          <p className="mt-1 text-[11px] text-argus-secondary">
            green = correct · red = wrong-supported (dangerous) · amber = wrong-flagged · grey = unsure
          </p>
        </div>
      )}

      {data.checkin_trend.length > 0 && (
        <div className="mt-4">
          <p className="mb-1 text-xs font-medium text-argus-secondary">Recent check-ins</p>
          <ul className="space-y-1 text-xs text-argus-secondary">
            {data.checkin_trend.slice(0, 4).map((c) => (
              <li key={c.week_bucket}>
                <span className="font-medium text-argus-primary">{c.week_bucket}</span>
                {typeof c.responses["would_keep_using"] === "string"
                  ? ` — keep using: ${c.responses["would_keep_using"]}`
                  : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-argus border border-argus-border-subtle p-3">
      <p className="text-[11px] uppercase tracking-wide text-argus-secondary">{label}</p>
      <p className="mt-1 text-lg font-semibold text-argus-primary">{value}</p>
      <p className="text-[11px] text-argus-secondary">{sub}</p>
    </div>
  );
}

function Bar({ pct, className, title }: { pct: number; className: string; title: string }) {
  if (pct <= 0) return null;
  return <span className={className} style={{ width: `${pct}%` }} title={title} />;
}
