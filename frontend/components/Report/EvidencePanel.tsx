"use client";

import { formatSourceLabel, similarityStrengthDots } from "@/lib/formatters";

export type EvidenceItem = {
  kind?: string;
  chunk_id?: string;
  evidence_id?: string;
  quote?: string;
  filename?: string;
  file_type?: string;
  similarity?: number;
  source_url?: string;
  url?: string;
  title?: string;
  snippet?: string;
  task_id?: number;
  finding_summary?: string;
  page?: number | null;
};

function DotBar({ filled }: { filled: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-hidden>
      {[0, 1, 2, 3].map((i) => (
        <span
          key={i}
          className={`h-1.5 w-1.5 rounded-full ${i < filled ? "bg-argus-accent" : "bg-argus-border-moderate"}`}
        />
      ))}
    </span>
  );
}

export default function EvidencePanel({ items }: { items: EvidenceItem[] }) {
  if (!items?.length) {
    return (
      <div className="mb-8 rounded-[14px] border border-dashed border-argus-border-subtle bg-canvas/40 p-6 text-sm text-argus-tertiary">
        No reference excerpts were bundled for this run. Add documents or URLs before running, or check
        retrieval coverage.
      </div>
    );
  }

  return (
    <div className="mb-10 rounded-[14px] border border-argus-border-subtle bg-surface p-6 shadow-argus-sm">
      <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
        Reference materials
      </p>
      <p className="mb-4 text-xs text-argus-tertiary">
        Excerpts and web citations used in the evidence bundle. Quotes are drawn from retrieved or fetched
        text.
      </p>
      <ul className="max-h-[28rem] space-y-4 overflow-y-auto pr-1">
        {items.map((item, i) => {
          const key = `ev-${i}-${formatSourceLabel(item).slice(0, 20)}`;
          if (item.kind === "web" || (item.url && !item.chunk_id)) {
            const href = item.url || "#";
            const label = formatSourceLabel(item);
            return (
              <li
                key={key}
                className="rounded-[12px] border border-argus-border-subtle bg-canvas/30 p-4 text-sm"
              >
                <div className="font-semibold text-argus-primary">
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-argus-accent hover:underline"
                  >
                    {item.title || label || "Web source"}
                  </a>
                </div>
                {item.snippet ? (
                  <p className="mt-2 text-xs italic leading-relaxed text-argus-tertiary">{item.snippet}</p>
                ) : null}
              </li>
            );
          }
          const srcLabel = formatSourceLabel(item);
          const { filled, label: simLabel } = similarityStrengthDots(item.similarity);
          return (
            <li
              key={key}
              className="rounded-[12px] border border-argus-border-subtle bg-canvas/30 p-4 text-sm"
            >
              <div className="flex flex-wrap items-center gap-2 text-xs text-argus-tertiary">
                <span className="font-medium text-argus-primary">{srcLabel}</span>
                {item.page != null ? <span>Page {item.page}</span> : null}
                {item.similarity != null ? (
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-argus-neutral-subtle px-2 py-0.5 text-[10px] text-argus-secondary">
                    <DotBar filled={filled} />
                    {simLabel}
                  </span>
                ) : null}
                {item.source_url ? (
                  <a
                    href={item.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-argus-accent hover:underline"
                  >
                    View source
                  </a>
                ) : null}
              </div>
              <blockquote className="mt-3 border-l-2 border-argus-success-border pl-3 text-sm italic text-argus-secondary">
                {item.quote || "(no excerpt)"}
              </blockquote>
              {item.finding_summary ? (
                <p className="mt-2 text-[11px] text-argus-tertiary">Context: {item.finding_summary}</p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
