"use client";

import { useEffect, useState } from "react";

import { createArtifact, exportArtifactDocx, listArtifacts } from "@/lib/api";
import type { Artifact, ArtifactStatus, ArtifactType, SessionDetail } from "@/lib/types";

import ArtifactCommentAffordance from "../Comments/ArtifactCommentAffordance";

type Tab = "memos" | "decks" | "models" | "charts";

const STATUS_TONE: Record<ArtifactStatus, string> = {
  draft: "bg-elevated text-argus-tertiary border-argus-border-subtle",
  review: "bg-argus-web-bg text-argus-web border-argus-web-border",
  final: "bg-argus-firm-bg text-argus-firm border-argus-firm-border",
};

const TYPE_ICON: Record<Tab, React.ReactNode> = {
  memos: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M9 13h6M9 17h4" />
    </svg>
  ),
  decks: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <rect x="3" y="4" width="18" height="14" rx="1" />
      <path d="M3 10h18M12 18v3M9 21h6" />
    </svg>
  ),
  models: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <rect x="3" y="3" width="18" height="18" rx="1" />
      <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
    </svg>
  ),
  charts: (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M3 3v18h18M7 14l3-3 3 3 5-7" />
    </svg>
  ),
};

const TAB_TO_TYPE: Record<Tab, ArtifactType> = {
  memos: "memo",
  decks: "deck",
  models: "model",
  charts: "chart",
};

function fmtRelative(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function ArtifactsRail({
  session,
  onOpenArtifact,
}: {
  session: SessionDetail;
  onOpenArtifact?: (artifactId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("memos");
  const [artifacts, setArtifacts] = useState<Artifact[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const refresh = async () => {
    try {
      const data = await listArtifacts(session.id);
      setArtifacts(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load artifacts");
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.id]);

  const visible = (artifacts ?? []).filter((a) => a.type === TAB_TO_TYPE[tab]);

  const handleExport = async (a: Artifact) => {
    setBusyId(a.id);
    try {
      const blob = await exportArtifactDocx(a.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${a.title.replace(/[^\w\s.-]/g, "_").slice(0, 60)}.docx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setBusyId(null);
    }
  };

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      const a = await createArtifact(session.id, "memo");
      await refresh();
      if (onOpenArtifact) onOpenArtifact(a.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create memo");
    } finally {
      setCreating(false);
    }
  };

  return (
    <aside className="argus-pane-artifacts flex flex-col">
      <div className="sticky top-0 z-10 border-b border-argus-border-subtle bg-[var(--bg-rail)] px-3 pt-3 pb-2">
        <div className="argus-label mb-2 flex items-center justify-between">
          <span>Artifacts</span>
          <span className="font-mono tabular-nums normal-case tracking-normal text-argus-tertiary">
            {artifacts?.length ?? 0}
          </span>
        </div>

        <div className="flex border-b border-argus-border-subtle text-[11px]">
          {([
            ["memos", "Memos"],
            ["decks", "Decks"],
            ["models", "Models"],
            ["charts", "Charts"],
          ] as const).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              className={`-mb-px border-b-2 px-2 py-1.5 transition-colors ${
                tab === k
                  ? "border-argus-primary font-semibold text-argus-primary"
                  : "border-transparent text-argus-tertiary hover:text-argus-secondary"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error ? (
        <p className="m-2 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[11px] text-argus-contested">
          {error}
        </p>
      ) : null}

      <div className="flex-1 space-y-px bg-argus-border-subtle/40 p-px">
        {!artifacts ? (
          <p className="bg-[var(--bg-rail)] p-4 text-[11px] text-argus-tertiary">Loading…</p>
        ) : visible.length === 0 ? (
          <p className="bg-[var(--bg-rail)] p-4 text-[11px] leading-relaxed text-argus-tertiary">
            No {tab} yet.{" "}
            {tab === "memos"
              ? 'Click "Generate from conversation" below to materialize a memo from the current report.'
              : "Decks/models/charts ship in v1."}
          </p>
        ) : (
          visible.map((a) => (
            <article
              key={a.id}
              className="border-l-2 border-argus-border-subtle bg-surface px-3 py-2 transition-colors hover:border-argus-accent"
            >
              <div className="mb-1 flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-1.5 text-argus-tertiary">
                  {TYPE_ICON[tab]}
                  <span className="text-[10px] font-semibold uppercase tracking-wider">
                    {a.type}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  {/* W16/D4: artifact-level comment affordance.
                      Renders nothing when the workspace shell hasn't
                      mounted the CommentsController, so existing
                      previews keep working. */}
                  <ArtifactCommentAffordance
                    artifactId={a.id}
                    label={`${a.type}: ${a.title}`}
                  />
                  <span className={`rounded-sm border px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${STATUS_TONE[a.status]}`}>
                    {a.status}
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => onOpenArtifact?.(a.id)}
                className="block w-full text-left font-serif text-[13px] leading-snug text-argus-primary hover:text-argus-accent"
              >
                {a.title}
              </button>
              <div className="mt-1.5 flex items-center justify-between text-[10px] text-argus-tertiary">
                <span className="font-mono tabular-nums">{fmtRelative(a.updated_at)}</span>
                <button
                  type="button"
                  onClick={() => void handleExport(a)}
                  disabled={busyId === a.id || a.type !== "memo"}
                  className="font-medium text-argus-accent hover:underline disabled:opacity-40"
                >
                  {busyId === a.id ? "Exporting…" : "Export DOCX"}
                </button>
              </div>
            </article>
          ))
        )}
      </div>

      <div className="sticky bottom-0 border-t border-argus-border-subtle bg-[var(--bg-rail)] p-2">
        <button
          type="button"
          onClick={() => void handleCreate()}
          disabled={creating || tab !== "memos"}
          className="w-full rounded-sm border border-argus-border-moderate bg-surface px-2 py-1.5 text-[11px] font-medium text-argus-primary hover:border-argus-primary disabled:opacity-50"
        >
          {creating
            ? "Generating…"
            : tab === "memos"
              ? "+ Generate memo from conversation"
              : `${tab.slice(0, -1)} generation in v1`}
        </button>
      </div>
    </aside>
  );
}
