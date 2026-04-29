"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { listSessions } from "@/lib/api";
import type { Session } from "@/lib/types";

function statusTone(status: Session["status"]): { dot: string; label: string } {
  if (status === "complete") return { dot: "bg-argus-success", label: "Complete" };
  if (status === "processing" || status === "pending")
    return { dot: "bg-argus-warning animate-pulse", label: "Processing" };
  if (status === "failed") return { dot: "bg-argus-danger", label: "Failed" };
  if (status === "insufficient") return { dot: "bg-argus-warning", label: "Insufficient" };
  return { dot: "bg-argus-neutral", label: "Draft" };
}

function modeLabel(mode?: string): string {
  if (!mode || mode === "general") return "General";
  return mode
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function RecentEngagements() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const data = await listSessions();
        if (alive) setSessions(data);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "Failed to load engagements");
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  if (error) {
    // Quietly fail — home page should still work without the engagements list.
    return null;
  }

  if (!sessions) {
    return (
      <div className="mt-12 w-full">
        <div className="text-center text-[11px] uppercase tracking-[0.06em] text-argus-tertiary">
          Recent engagements
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-argus-md border border-argus-border-subtle bg-surface"
            />
          ))}
        </div>
      </div>
    );
  }

  if (sessions.length === 0) return null;

  const visible = sessions.slice(0, 6);

  return (
    <section className="mt-12 w-full" aria-label="Recent engagements">
      <div className="mb-3 flex items-center justify-between text-[11px] uppercase tracking-[0.06em] text-argus-tertiary">
        <span>Recent engagements</span>
        <span className="text-argus-tertiary/70">{sessions.length} total</span>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {visible.map((s) => {
          const tone = statusTone(s.status);
          const meta = s.metadata ?? {};
          const clientLabel = meta.client_label;
          const isDemo = Boolean(meta.demo);
          return (
            <li key={s.id}>
              <Link
                href={`/sessions/${s.id}`}
                className="group block h-full rounded-argus-md border border-argus-border-subtle bg-surface p-3 transition-colors hover:border-argus-border-moderate hover:bg-elevated"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-argus-tertiary">
                    <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} aria-hidden />
                    {tone.label}
                  </span>
                  <span className="text-[10px] text-argus-tertiary">
                    {modeLabel(s.report_mode)}
                  </span>
                </div>
                <h3 className="mt-2 line-clamp-2 text-[13px] font-medium text-argus-primary group-hover:text-argus-primary">
                  {s.title}
                </h3>
                {s.recommendation_preview ? (
                  <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-argus-secondary">
                    {s.recommendation_preview}
                  </p>
                ) : (
                  <p className="mt-1.5 line-clamp-1 text-[11px] text-argus-tertiary">
                    {s.query}
                  </p>
                )}
                {clientLabel || isDemo ? (
                  <div className="mt-2.5 flex items-center gap-2 text-[10px] text-argus-tertiary">
                    {clientLabel ? <span>{clientLabel}</span> : null}
                    {isDemo ? (
                      <span className="inline-flex items-center gap-1 rounded-argus-sm bg-argus-info-subtle px-1.5 py-0.5 text-argus-accent">
                        Demo
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
