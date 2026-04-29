"use client";

import type { SessionDetail } from "@/lib/types";

function reportModeLabel(mode?: string): string {
  if (!mode || mode === "general") return "Strategic question";
  return mode
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function ClientBanner({ session }: { session: SessionDetail }) {
  const meta = session.metadata ?? {};
  const clientLabel = meta.client_label?.trim();
  const engagementType = meta.engagement_type?.trim();
  const isDemo = Boolean(meta.demo);

  // Hide banner entirely if no engagement framing set — keeps regular runs clean.
  if (!clientLabel && !engagementType) return null;

  return (
    <div
      className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-argus-md border border-argus-border-subtle bg-elevated px-4 py-2.5 text-[12px]"
      role="note"
      aria-label="Engagement details"
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-argus-secondary">
        {clientLabel ? (
          <span className="font-medium text-argus-primary">{clientLabel}</span>
        ) : null}
        {engagementType ? <span>{engagementType}</span> : null}
        <span className="text-argus-tertiary">{reportModeLabel(session.report_mode)}</span>
        <span className="text-argus-tertiary">Confidential</span>
      </div>
      {isDemo ? (
        <span className="inline-flex items-center gap-1.5 rounded-argus-sm border border-argus-info-border bg-argus-info-subtle px-2 py-1 text-[11px] font-medium text-argus-accent">
          <span className="h-1.5 w-1.5 rounded-full bg-argus-accent" aria-hidden />
          Demo workspace · fictionalized data
        </span>
      ) : null}
    </div>
  );
}
