"use client";

import { useEffect, useState } from "react";

import { deleteSource, patchSource } from "@/lib/api";
import type { SourceItem, SourceScope, TrustLevel } from "@/lib/types";

const TRUST_TONE: Record<TrustLevel, string> = {
  firm_vetted: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  credible_external: "border-argus-credible-border bg-argus-credible-bg text-argus-credible",
  web_general: "border-argus-web-border bg-argus-web-bg text-argus-web",
  contested: "border-argus-contested-border bg-argus-contested-bg text-argus-contested",
};

const TRUST_LABEL: Record<TrustLevel, string> = {
  firm_vetted: "Firm-vetted",
  credible_external: "Credible external",
  web_general: "Web-general",
  contested: "Contested",
};

const TRUST_HINT: Record<TrustLevel, string> = {
  firm_vetted: "Internal / pre-approved",
  credible_external: "FT / peer-review / regulator",
  web_general: "Public web",
  contested: "Single-source / disputed",
};

function fmtSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso.slice(0, 10);
  }
}

function CloseIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

export default function SourceDetailDrawer({
  source,
  onClose,
  onUpdated,
  onDeleted,
  canPromoteFirm,
}: {
  source: SourceItem | null;
  onClose: () => void;
  onUpdated: (next: SourceItem) => void;
  onDeleted: (id: string) => void;
  /** Whether the current viewer can promote scope from engagement → firm. */
  canPromoteFirm?: boolean;
}) {
  const [notes, setNotes] = useState("");
  const [trust, setTrust] = useState<TrustLevel>("credible_external");
  const [scope, setScope] = useState<SourceScope>("engagement");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!source) return;
    setNotes(source.notes ?? "");
    setTrust(source.trust_level);
    setScope(source.scope);
    setDirty(false);
    setError(null);
    setConfirmDelete(false);
  }, [source]);

  if (!source) return null;

  const handleSave = async () => {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      const patch: Parameters<typeof patchSource>[1] = {};
      if (notes !== (source.notes ?? "")) patch.notes = notes;
      if (trust !== source.trust_level) patch.trust_level = trust;
      if (scope !== source.scope) patch.scope = scope;
      if (Object.keys(patch).length === 0) {
        setBusy(false);
        return;
      }
      const updated = await patchSource(source.id, patch);
      onUpdated(updated);
      setDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!source) return;
    setBusy(true);
    setError(null);
    try {
      await deleteSource(source.id);
      onDeleted(source.id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
      setBusy(false);
    }
  };

  return (
    <>
      <div aria-hidden onClick={onClose} className="fixed inset-0 z-40 bg-black/40" />
      <aside
        role="dialog"
        aria-label={`Source ${source.filename}`}
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col overflow-hidden border-l border-argus-border-subtle bg-canvas shadow-argus-xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-argus-border-subtle bg-surface px-5 py-4">
          <div className="min-w-0 flex-1">
            <div className="argus-label">Source detail</div>
            <h2 className="mt-1 break-words font-serif text-[18px] font-semibold text-argus-primary">
              {source.filename}
            </h2>
            <div className="mt-1 flex items-center gap-2 text-[10px] text-argus-tertiary">
              <span className="font-mono uppercase tabular-nums">{source.file_type}</span>
              <span>·</span>
              <span className="font-mono tabular-nums">{source.chunk_count} chunks</span>
              <span>·</span>
              <span className="font-mono tabular-nums">{fmtSize(source.original_size)}</span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-argus-sm p-1 text-argus-tertiary hover:bg-elevated hover:text-argus-primary"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {/* Trust tier */}
          <section className="mb-5">
            <div className="argus-label mb-2">Trust tier</div>
            <div className="grid grid-cols-2 gap-2">
              {(Object.keys(TRUST_LABEL) as TrustLevel[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => {
                    setTrust(t);
                    setDirty(true);
                  }}
                  className={`rounded-sm border px-2 py-1.5 text-left text-[11px] transition-all ${
                    trust === t
                      ? `${TRUST_TONE[t]} ring-2 ring-offset-1 ring-argus-accent`
                      : "border-argus-border-subtle bg-surface text-argus-secondary hover:border-argus-border-moderate"
                  }`}
                >
                  <div className="font-semibold">{TRUST_LABEL[t]}</div>
                  <div className="text-[10px] opacity-80">{TRUST_HINT[t]}</div>
                </button>
              ))}
            </div>
          </section>

          {/* Scope */}
          <section className="mb-5">
            <div className="argus-label mb-2">Scope</div>
            <div className="flex rounded-sm border border-argus-border-subtle bg-surface p-0.5 text-[11px]">
              {(["engagement", "firm"] as const).map((s) => {
                const disabled = s === "firm" && canPromoteFirm === false && source.scope !== "firm";
                return (
                  <button
                    key={s}
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      if (disabled) return;
                      setScope(s);
                      setDirty(true);
                    }}
                    className={`flex-1 rounded-sm px-2 py-1 transition-colors ${
                      scope === s
                        ? "bg-argus-primary text-argus-inverse"
                        : "text-argus-secondary hover:text-argus-primary disabled:cursor-not-allowed disabled:opacity-50"
                    }`}
                    title={disabled ? "Only leads can promote to firm-wide" : undefined}
                  >
                    {s === "engagement" ? "This engagement" : "Firm-wide library"}
                  </button>
                );
              })}
            </div>
            <p className="mt-1 text-[10px] text-argus-tertiary">
              {scope === "firm"
                ? "Visible across the firm. Used by any engagement that opts into the library."
                : "Only this engagement can use this source."}
            </p>
          </section>

          {/* Notes */}
          <section className="mb-5">
            <label className="argus-label mb-2 block" htmlFor="src-notes">
              Notes
            </label>
            <textarea
              id="src-notes"
              rows={4}
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value);
                setDirty(true);
              }}
              placeholder="Why this source is relevant, caveats, etc."
              className="w-full resize-y rounded-sm border border-argus-border-moderate bg-surface px-2 py-1.5 text-[12px] leading-snug placeholder:text-argus-quaternary focus:border-argus-border-strong focus:outline-none"
            />
          </section>

          {/* Stats */}
          <section className="mb-5 rounded-sm border border-argus-border-subtle bg-elevated p-3 text-[11px]">
            <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1.5">
              <dt className="text-argus-tertiary">Added</dt>
              <dd className="font-mono tabular-nums text-argus-secondary">{fmtDate(source.created_at)}</dd>
              <dt className="text-argus-tertiary">Chunks</dt>
              <dd className="font-mono tabular-nums text-argus-secondary">{source.chunk_count}</dd>
              <dt className="text-argus-tertiary">Size</dt>
              <dd className="font-mono tabular-nums text-argus-secondary">{fmtSize(source.original_size)}</dd>
              <dt className="text-argus-tertiary">Type</dt>
              <dd className="font-mono uppercase tabular-nums text-argus-secondary">{source.file_type}</dd>
              {source.source_url ? (
                <>
                  <dt className="text-argus-tertiary">URL</dt>
                  <dd className="min-w-0">
                    <a
                      href={source.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block truncate text-argus-accent hover:underline"
                    >
                      {source.source_url}
                    </a>
                  </dd>
                </>
              ) : null}
            </dl>
          </section>

          {error ? (
            <p className="mb-3 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested">
              {error}
            </p>
          ) : null}

          {/* Danger zone */}
          <section className="border-t border-argus-border-subtle pt-3">
            <div className="argus-label mb-2" style={{ color: "var(--text-oxblood)" }}>
              Danger zone
            </div>
            {confirmDelete ? (
              <div className="flex items-center justify-between gap-2 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-2 text-[11px]">
                <span className="text-argus-contested">Permanently remove this source and all its chunks?</span>
                <span className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setConfirmDelete(false)}
                    disabled={busy}
                    className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-1 text-argus-secondary hover:border-argus-border-moderate disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete()}
                    disabled={busy}
                    className="rounded-sm border border-argus-contested-border bg-argus-contested px-2 py-1 font-semibold text-argus-inverse hover:opacity-90 disabled:opacity-50"
                  >
                    {busy ? "Deleting…" : "Delete"}
                  </button>
                </span>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmDelete(true)}
                disabled={busy}
                className="rounded-sm border border-argus-contested-border bg-surface px-2 py-1 text-[11px] text-argus-contested hover:bg-argus-contested-bg disabled:opacity-50"
              >
                Delete source…
              </button>
            )}
          </section>
        </div>

        <footer className="flex items-center justify-between gap-2 border-t border-argus-border-subtle bg-[var(--bg-rail)] px-5 py-3">
          <span className="text-[10px] text-argus-tertiary">
            {dirty ? "Unsaved changes" : "Up to date"}
          </span>
          <span className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-sm border border-argus-border-moderate bg-surface px-3 py-1.5 text-[12px] text-argus-secondary hover:border-argus-primary"
            >
              Close
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={busy || !dirty}
              className="rounded-sm border border-argus-border-strong bg-argus-primary px-3 py-1.5 text-[12px] font-semibold text-argus-inverse hover:opacity-90 disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save"}
            </button>
          </span>
        </footer>
      </aside>
    </>
  );
}
