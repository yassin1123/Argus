"use client";

import { useEffect, useId, useState } from "react";

import {
  type ChunkPreview,
  type FirmContent,
  editFirmContent,
  getFirmContent,
  retireFirmContent,
} from "@/lib/api/firmLibrary";

const CATEGORY_LABEL: Record<string, string> = {
  playbook: "Playbook",
  sector_primer: "Sector primer",
  prior_report: "Prior report",
  framework: "Framework",
  methodology: "Methodology",
  other: "Other",
};

export interface LibraryDetailPanelProps {
  firmId: string;
  contentId: string;
  isAdmin: boolean;
  onClose: () => void;
  /** Called after a successful edit or retire so the parent list refreshes. */
  onMutated?: (next: FirmContent) => void;
}

export default function LibraryDetailPanel({
  firmId,
  contentId,
  isAdmin,
  onClose,
  onMutated,
}: LibraryDetailPanelProps) {
  const [data, setData] = useState<{ firm_content: FirmContent; chunk_preview: ChunkPreview[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editModes, setEditModes] = useState("");
  const [editSectors, setEditSectors] = useState("");
  const [confirmRetire, setConfirmRetire] = useState(false);
  const [busy, setBusy] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const titleId = useId();
  const descId = useId();
  const modesId = useId();
  const sectorsId = useId();

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const r = await getFirmContent(firmId, contentId);
        if (!alive) return;
        setData(r);
        setError(null);
      } catch (e) {
        if (!alive) return;
        setError(e instanceof Error ? e.message : "Failed to load");
      }
    })();
    return () => {
      alive = false;
    };
  }, [firmId, contentId]);

  // Seed the edit form from the loaded record when the user clicks Edit.
  const startEdit = () => {
    if (!data) return;
    setEditTitle(data.firm_content.title);
    setEditDescription(data.firm_content.description ?? "");
    setEditModes(data.firm_content.intended_modes.join(", "));
    setEditSectors(data.firm_content.sector_tags.join(", "));
    setEditing(true);
    setStatusMsg(null);
  };

  const saveEdit = async () => {
    if (!data) return;
    setBusy(true);
    setStatusMsg(null);
    try {
      const updated = await editFirmContent(firmId, contentId, {
        title: editTitle,
        description: editDescription,
        intendedModes: editModes
          .split(",")
          .map((m) => m.trim())
          .filter(Boolean),
        sectorTags: editSectors
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setData({ ...data, firm_content: updated });
      setEditing(false);
      setStatusMsg("Saved.");
      onMutated?.(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const doRetire = async () => {
    if (!data) return;
    setBusy(true);
    setStatusMsg(null);
    try {
      const r = await retireFirmContent(firmId, contentId);
      setData({ ...data, firm_content: r.firm_content });
      setConfirmRetire(false);
      setStatusMsg(r.already_retired ? "Already retired." : "Retired.");
      onMutated?.(r.firm_content);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Retire failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Firm content detail"
      className="fixed inset-0 z-40 flex"
      data-testid="firm-library-detail"
    >
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close detail panel"
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
      />
      {/* Slide-out panel */}
      <aside
        className="ml-auto h-full w-full max-w-[560px] overflow-y-auto border-l border-argus-border-moderate bg-surface shadow-popover"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-argus-border-subtle px-5 py-3">
          <h2 className="font-serif text-[18px] font-semibold text-argus-primary">
            Library item
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-[14px] text-argus-tertiary hover:text-argus-primary"
          >
            ×
          </button>
        </header>

        {error ? (
          <p
            role="alert"
            className="m-5 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested"
          >
            {error}
          </p>
        ) : null}

        {!data ? (
          <p className="p-5 text-[13px] text-argus-tertiary">Loading…</p>
        ) : (
          <div className="space-y-5 px-5 py-4">
            {statusMsg ? (
              <p
                role="status"
                className="rounded-sm border border-argus-firm-border bg-argus-firm-bg px-2 py-1 text-[12px] text-argus-firm"
              >
                {statusMsg}
              </p>
            ) : null}

            {/* Metadata block */}
            {!editing ? (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-serif text-[20px] font-semibold text-argus-primary">
                    {data.firm_content.title}
                  </h3>
                  {data.firm_content.retired_at ? (
                    <span className="rounded-sm border border-argus-contested-border bg-argus-contested-bg px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-argus-contested">
                      Retired
                    </span>
                  ) : null}
                </div>
                <div className="text-[12px] text-argus-tertiary">
                  <span className="rounded-sm border border-argus-border-subtle bg-elevated px-1.5 py-0.5">
                    {CATEGORY_LABEL[data.firm_content.category] ?? data.firm_content.category}
                  </span>
                  <span className="ml-2 font-mono tabular-nums">
                    {data.firm_content.chunk_count} chunks
                  </span>
                </div>
                {data.firm_content.description ? (
                  <p className="whitespace-pre-line text-[13px] text-argus-secondary">
                    {data.firm_content.description}
                  </p>
                ) : null}
                {data.firm_content.intended_modes.length > 0 ? (
                  <div className="text-[11px] text-argus-tertiary">
                    <span className="argus-label mr-1">Modes</span>
                    {data.firm_content.intended_modes.map((m) => (
                      <span
                        key={m}
                        className="ml-1 rounded-sm bg-elevated px-1 py-0.5 font-mono"
                      >
                        {m}
                      </span>
                    ))}
                  </div>
                ) : null}
                {data.firm_content.sector_tags.length > 0 ? (
                  <div className="text-[11px] text-argus-tertiary">
                    <span className="argus-label mr-1">Sectors</span>
                    {data.firm_content.sector_tags.map((s) => (
                      <span
                        key={s}
                        className="ml-1 rounded-sm bg-elevated px-1 py-0.5"
                      >
                        {s}
                      </span>
                    ))}
                  </div>
                ) : null}
                <div className="text-[11px] text-argus-quaternary">
                  Source file: {data.firm_content.source_filename ?? "—"}
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div>
                  <label htmlFor={titleId} className="argus-label mb-1 block">
                    Title
                  </label>
                  <input
                    id={titleId}
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    className="w-full rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 text-[13px] focus:border-argus-border-strong focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor={descId} className="argus-label mb-1 block">
                    Description
                  </label>
                  <textarea
                    id={descId}
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    rows={3}
                    className="w-full resize-y rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 text-[13px] focus:border-argus-border-strong focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor={modesId} className="argus-label mb-1 block">
                    Modes (comma-separated)
                  </label>
                  <input
                    id={modesId}
                    type="text"
                    value={editModes}
                    onChange={(e) => setEditModes(e.target.value)}
                    className="w-full rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 text-[13px] focus:border-argus-border-strong focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor={sectorsId} className="argus-label mb-1 block">
                    Sector tags (comma-separated)
                  </label>
                  <input
                    id={sectorsId}
                    type="text"
                    value={editSectors}
                    onChange={(e) => setEditSectors(e.target.value)}
                    className="w-full rounded-sm border border-argus-border-moderate bg-surface px-2 py-1 text-[13px] focus:border-argus-border-strong focus:outline-none"
                  />
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={busy || !editTitle.trim()}
                    onClick={saveEdit}
                    className="rounded-sm bg-argus-primary px-3 py-1 text-[12px] font-semibold text-argus-inverse disabled:opacity-50"
                  >
                    {busy ? "Saving…" : "Save"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditing(false)}
                    className="rounded-sm border border-argus-border-subtle px-3 py-1 text-[12px] text-argus-secondary"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Chunks preview */}
            {data.chunk_preview.length > 0 ? (
              <section>
                <h4 className="argus-label mb-2">First {data.chunk_preview.length} chunks</h4>
                <ul className="space-y-2">
                  {data.chunk_preview.map((c) => (
                    <li
                      key={c.id}
                      className="rounded-sm border border-argus-border-subtle bg-elevated px-2 py-1.5 text-[12px]"
                    >
                      {c.section_heading ? (
                        <div className="mb-0.5 text-[10px] uppercase tracking-wide text-argus-tertiary">
                          {c.section_heading}
                        </div>
                      ) : null}
                      <p className="whitespace-pre-wrap text-argus-secondary line-clamp-4">
                        {c.content}
                      </p>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {/* Retrieval stats — Day 3 hard rule says skip if heavy.
                The chunks→evidence_objects→claim_support_rows join isn't
                cheap enough on this dev DB to render in the panel
                today. Show a placeholder instead and revisit when we
                have a materialised view (Phase 2 polish). */}
            <section className="text-[11px] text-argus-quaternary">
              Citation tracking coming soon.
            </section>

            {/* Admin actions */}
            {isAdmin ? (
              <section className="border-t border-argus-border-subtle pt-3">
                <h4 className="argus-label mb-2">Admin actions</h4>
                <div className="flex flex-wrap gap-2">
                  {!editing ? (
                    <button
                      type="button"
                      onClick={startEdit}
                      disabled={busy}
                      className="rounded-sm border border-argus-border-moderate bg-surface px-3 py-1 text-[12px] hover:bg-elevated disabled:opacity-50"
                      data-testid="firm-library-edit-button"
                    >
                      Edit metadata
                    </button>
                  ) : null}
                  {!data.firm_content.retired_at ? (
                    confirmRetire ? (
                      <div className="flex flex-wrap items-center gap-2 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1">
                        <span className="text-[12px] text-argus-contested">
                          Retire &ldquo;{data.firm_content.title}&rdquo;? This excludes it from
                          future retrieval but preserves historical citations.
                        </span>
                        <button
                          type="button"
                          onClick={doRetire}
                          disabled={busy}
                          className="rounded-sm bg-argus-contested px-2 py-1 text-[11px] font-semibold text-argus-inverse disabled:opacity-50"
                        >
                          {busy ? "Retiring…" : "Confirm retire"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmRetire(false)}
                          className="text-[11px] text-argus-tertiary hover:text-argus-primary"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmRetire(true)}
                        disabled={busy}
                        className="rounded-sm border border-argus-contested-border bg-argus-contested-bg px-3 py-1 text-[12px] text-argus-contested hover:opacity-90 disabled:opacity-50"
                        data-testid="firm-library-retire-button"
                      >
                        Retire
                      </button>
                    )
                  ) : null}
                </div>
              </section>
            ) : (
              <section className="border-t border-argus-border-subtle pt-3 text-[11px] text-argus-tertiary">
                Editing and retiring library content requires firm-admin access.
              </section>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}
