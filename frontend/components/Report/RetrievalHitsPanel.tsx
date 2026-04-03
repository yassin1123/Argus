"use client";

export interface RetrievalHit {
  chunk_id?: string;
  text?: string;
  chunk_index?: number;
  similarity?: number;
  filename?: string;
  file_type?: string;
  page?: number | null;
  source_url?: string | null;
}

export interface RetrievalTaskSnapshot {
  task_id?: number;
  question?: string;
  hits?: RetrievalHit[];
}

function relevance(sim: number | undefined): string {
  if (sim == null) return "";
  if (sim >= 0.35) return "Strong match";
  if (sim >= 0.15) return "Moderate match";
  return "Weak match";
}

export default function RetrievalHitsPanel({ snapshots }: { snapshots: RetrievalTaskSnapshot[] }) {
  if (!snapshots?.length) return null;
  return (
    <section className="rounded-[14px] border border-argus-border-subtle bg-surface p-4 shadow-argus-sm">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-argus-tertiary">
        Retrieval highlights
      </h3>
      <p className="mt-1 text-xs text-argus-tertiary">
        Passages retrieved from your uploads for each research task.
      </p>
      <div className="mt-4 space-y-6">
        {snapshots.map((snap, ti) => (
          <div key={ti} className="border-t border-argus-border-subtle pt-4 first:border-t-0 first:pt-0">
            <p className="text-xs font-medium text-argus-secondary">
              {snap.question ?? `Research task ${snap.task_id ?? ti}`}
            </p>
            <ul className="mt-2 space-y-2 text-sm">
              {(snap.hits ?? []).slice(0, 8).map((h, hi) => (
                <li
                  key={hi}
                  className="rounded-[12px] border border-argus-border-subtle bg-canvas/40 px-3 py-2"
                >
                  <div className="flex flex-wrap items-center gap-2 text-xs text-argus-tertiary">
                    <span className="font-medium text-argus-primary">{h.filename || "Document"}</span>
                    {h.page != null ? <span>Page {h.page}</span> : null}
                    {h.file_type ? <span>({h.file_type})</span> : null}
                    {h.similarity != null ? (
                      <span className="rounded-full bg-argus-neutral-subtle px-2 py-0.5 text-[10px] text-argus-secondary">
                        {relevance(h.similarity)}
                      </span>
                    ) : null}
                    {h.source_url ? (
                      <a
                        href={h.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-argus-accent hover:underline"
                      >
                        Open link
                      </a>
                    ) : null}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[11px] italic text-argus-tertiary">{h.text}</p>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
