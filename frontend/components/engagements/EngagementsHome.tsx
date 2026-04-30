"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { createSession, listSessions } from "@/lib/api";
import type { Session } from "@/lib/types";

function statusTone(status: Session["status"]): { label: string; cls: string } {
  if (status === "complete") return { label: "Active", cls: "bg-argus-firm-bg text-argus-firm border-argus-firm-border" };
  if (status === "processing" || status === "pending")
    return { label: "Running", cls: "bg-argus-web-bg text-argus-web border-argus-web-border" };
  if (status === "failed") return { label: "Failed", cls: "bg-argus-contested-bg text-argus-contested border-argus-contested-border" };
  if (status === "insufficient") return { label: "Review", cls: "bg-argus-web-bg text-argus-web border-argus-web-border" };
  return { label: "Draft", cls: "bg-elevated text-argus-tertiary border-argus-border-subtle" };
}

function modeLabel(mode?: string): string {
  if (!mode || mode === "general") return "General";
  return mode.split("_").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function relativeTime(iso?: string): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

function NewEngagementBar() {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  const submit = async () => {
    const q = query.trim();
    if (!q || busy) return;
    setBusy(true);
    try {
      const { session_id } = await createSession(q);
      router.push(`/sessions/${session_id}/intake`);
    } catch {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-argus-md border border-argus-border-moderate bg-surface px-4 py-3 shadow-argus-sm">
      <div className="argus-label mb-2">New engagement</div>
      <div className="flex items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder="State the strategic question. e.g. What's the addressable market for GLP-1s in Southeast Asia by 2030?"
          className="flex-1 border-b border-transparent bg-transparent py-1 font-serif text-[15px] leading-snug text-argus-primary placeholder:text-argus-quaternary focus:border-argus-border-strong focus:outline-none"
        />
        <button
          type="button"
          disabled={!query.trim() || busy}
          onClick={() => void submit()}
          className="shrink-0 rounded-sm border border-argus-border-strong bg-argus-primary px-3 py-1.5 text-[12px] font-semibold text-argus-inverse transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "Creating…" : "Open engagement"}
        </button>
      </div>
    </div>
  );
}

function EngagementCard({ session }: { session: Session }) {
  const tone = statusTone(session.status);
  const meta = session.metadata ?? {};
  const client = meta.client_label ?? "Internal";
  const isDemo = Boolean(meta.demo);

  return (
    <Link
      href={`/sessions/${session.id}`}
      className="group block border-l-2 border-argus-border-subtle bg-surface px-4 py-3 transition-colors hover:border-argus-accent hover:bg-elevated"
    >
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px]">
        <span className="argus-label">{client}</span>
        <div className="flex items-center gap-1.5">
          {session.my_role ? (
            <span
              className="rounded-sm border border-argus-border-subtle bg-surface px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-argus-tertiary"
              title={`You are ${session.my_role} on this engagement`}
            >
              {session.my_role}
            </span>
          ) : null}
          {isDemo ? (
            <span className="rounded-sm bg-elevated px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-argus-tertiary">
              Demo
            </span>
          ) : null}
          <span className={`rounded-sm border px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${tone.cls}`}>
            {tone.label}
          </span>
        </div>
      </div>
      <h3 className="font-serif text-[16px] leading-snug text-argus-primary line-clamp-2">
        {session.title}
      </h3>
      {session.recommendation_preview ? (
        <p className="mt-1.5 line-clamp-2 text-[12px] leading-snug text-argus-secondary">
          {session.recommendation_preview}
        </p>
      ) : (
        <p className="mt-1.5 line-clamp-1 text-[12px] text-argus-tertiary">{session.query}</p>
      )}
      <div className="mt-2.5 flex items-center justify-between text-[10px] text-argus-tertiary">
        <div className="flex items-center gap-3">
          <span className="font-mono tabular-nums">{session.evidence_count ?? 0} sources</span>
          <span>{modeLabel(session.report_mode)}</span>
        </div>
        <span>{relativeTime(session.updated_at)}</span>
      </div>
    </Link>
  );
}

export default function EngagementsHome() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "active" | "draft">("all");

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

  const visible = useMemo(() => {
    if (!sessions) return [];
    if (filter === "active") return sessions.filter((s) => s.status === "complete" || s.status === "processing");
    if (filter === "draft") return sessions.filter((s) => s.status === "draft");
    return sessions;
  }, [sessions, filter]);

  return (
    <main className="mx-auto max-w-[1100px] px-8 py-8">
      <header className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="font-serif text-[28px] font-semibold text-argus-primary">Engagements</h1>
          <p className="mt-1 text-[13px] text-argus-tertiary">
            Each engagement accumulates sources, reasoning, and deliverables. Conversations are ephemeral; engagements stay.
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-sm border border-argus-border-subtle bg-surface p-0.5 text-[11px]">
          {(["all", "active", "draft"] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`rounded-sm px-2.5 py-1 transition-colors ${
                filter === f
                  ? "bg-argus-primary text-argus-inverse"
                  : "text-argus-secondary hover:text-argus-primary"
              }`}
            >
              {f === "all" ? "All" : f === "active" ? "Active" : "Drafts"}
            </button>
          ))}
        </div>
      </header>

      <div className="mb-6">
        <NewEngagementBar />
      </div>

      {error ? (
        <p className="text-[13px] text-argus-contested">{error}</p>
      ) : !sessions ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-24 animate-pulse border-l-2 border-argus-border-subtle bg-surface" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="rounded-argus-md border border-dashed border-argus-border-moderate p-8 text-center">
          <p className="font-serif text-[16px] text-argus-primary">No engagements yet</p>
          <p className="mt-1 text-[12px] text-argus-tertiary">
            Start one above. Or paste a strategic question and Argus will scope it.
          </p>
        </div>
      ) : (
        <div className="grid gap-px overflow-hidden border border-argus-border-subtle bg-argus-border-subtle">
          {visible.map((s) => (
            <EngagementCard key={s.id} session={s} />
          ))}
        </div>
      )}
    </main>
  );
}
