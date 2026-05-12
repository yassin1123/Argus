"use client";

import Link from "next/link";
import { useState } from "react";

import { createExport, downloadUrl } from "@/lib/api/sessionExports";
import type { SessionDetail } from "@/lib/types";

import TeamPanel from "./TeamPanel";

function ChevronLeft() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="m15 18-6-6 6-6" />
    </svg>
  );
}

function statusToneClass(status: SessionDetail["status"]): string {
  if (status === "complete") return "bg-argus-firm-bg text-argus-firm border-argus-firm-border";
  if (status === "processing" || status === "pending") return "bg-argus-web-bg text-argus-web border-argus-web-border";
  if (status === "failed") return "bg-argus-contested-bg text-argus-contested border-argus-contested-border";
  if (status === "insufficient") return "bg-argus-web-bg text-argus-web border-argus-web-border";
  return "bg-elevated text-argus-tertiary border-argus-border-subtle";
}

export default function WorkspaceTopBar({
  session,
  showWork,
  onToggleShowWork,
  collapseSource,
  onToggleSource,
  collapseArtifacts,
  onToggleArtifacts,
}: {
  session: SessionDetail;
  showWork: boolean;
  onToggleShowWork: () => void;
  collapseSource: boolean;
  onToggleSource: () => void;
  collapseArtifacts: boolean;
  onToggleArtifacts: () => void;
}) {
  const meta = session.metadata ?? {};
  const client = meta.client_label ?? "Internal";
  const role = session.my_role;
  const canManage = role === "lead";
  const isViewer = role === "viewer";
  const [teamOpen, setTeamOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  async function handleExportOnePagerHtml() {
    if (exporting) return;
    setExportError(null);
    setExporting(true);
    try {
      const created = await createExport(session.id, "one_pager", "html");
      if (created.status === "ready") {
        window.open(downloadUrl(session.id, created.artifact_id), "_blank", "noopener");
      } else if (created.status === "failed") {
        setExportError(created.failure_reason ?? "Export failed");
      } else {
        // 'generating' — synchronous render is the default for HTML, but
        // keep a fallback message in case the architecture transitions
        // to async dispatch later.
        setExportError("Render queued — refresh the artifacts panel shortly.");
      }
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <header className="argus-topbar">
      <Link
        href="/"
        className="flex items-center gap-1 text-[11px] text-argus-tertiary hover:text-argus-primary"
      >
        <ChevronLeft />
        <span>Engagements</span>
      </Link>

      <span className="h-3 w-px bg-argus-border-subtle" aria-hidden />

      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="argus-label">{client}</span>
        <span className="font-serif text-[14px] font-semibold text-argus-primary truncate">
          {session.title}
        </span>
        <span className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${statusToneClass(session.status)}`}>
          {session.status}
        </span>
        {isViewer ? (
          <span className="rounded-sm border border-argus-border-subtle bg-elevated px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-argus-tertiary" title="You have read-only access on this engagement">
            Viewer
          </span>
        ) : null}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setTeamOpen(true)}
          className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[11px] font-medium text-argus-secondary transition-colors hover:border-argus-primary hover:text-argus-primary"
          title="View engagement team"
        >
          Team
        </button>

        <button
          type="button"
          onClick={handleExportOnePagerHtml}
          disabled={exporting || isViewer}
          className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[11px] font-medium text-argus-secondary transition-colors hover:border-argus-primary hover:text-argus-primary disabled:cursor-not-allowed disabled:opacity-60"
          title={
            isViewer
              ? "Viewers cannot generate exports"
              : exportError
                ? `Last attempt: ${exportError}`
                : "Render a single-page 1-pager (HTML) and open it in a new tab"
          }
        >
          {exporting ? "Exporting…" : "Export → 1-pager"}
        </button>

        <button
          type="button"
          onClick={onToggleShowWork}
          aria-pressed={showWork}
          className={`rounded-sm border px-2 py-1 text-[11px] font-medium transition-colors ${
            showWork
              ? "border-argus-primary bg-argus-primary text-argus-inverse"
              : "border-argus-border-subtle bg-surface text-argus-secondary hover:border-argus-primary hover:text-argus-primary"
          }`}
          title="Reveal which models produced each section"
        >
          Show the work
        </button>

        <span className="h-3 w-px bg-argus-border-subtle" aria-hidden />

        <button
          type="button"
          onClick={onToggleSource}
          aria-pressed={!collapseSource}
          title="Toggle source rail"
          className="flex h-7 w-7 items-center justify-center rounded-sm border border-argus-border-subtle bg-surface text-argus-tertiary hover:border-argus-primary hover:text-argus-primary"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
            <rect x="3" y="3" width="18" height="18" />
            <path d="M9 3v18" />
          </svg>
        </button>
        <button
          type="button"
          onClick={onToggleArtifacts}
          aria-pressed={!collapseArtifacts}
          title="Toggle artifacts rail"
          className="flex h-7 w-7 items-center justify-center rounded-sm border border-argus-border-subtle bg-surface text-argus-tertiary hover:border-argus-primary hover:text-argus-primary"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
            <rect x="3" y="3" width="18" height="18" />
            <path d="M15 3v18" />
          </svg>
        </button>
      </div>

      <TeamPanel
        engagementId={session.id}
        canManage={canManage}
        open={teamOpen}
        onClose={() => setTeamOpen(false)}
      />
    </header>
  );
}
