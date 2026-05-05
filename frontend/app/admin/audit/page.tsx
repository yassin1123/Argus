"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import EmptyState from "@/components/ui/EmptyState";

export const dynamic = "force-dynamic";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type AuditEvent = {
  id: number;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  method: string | null;
  path: string | null;
  status_code: number | null;
  ip: string | null;
  payload: Record<string, unknown>;
  created_at: string | null;
};

type EventKind = "auth" | "source" | "artifact" | "engagement" | "session" | "other";

function kindOf(action: string): EventKind {
  if (action.startsWith("auth.")) return "auth";
  if (action.startsWith("source.") || action.startsWith("library.")) return "source";
  if (action.startsWith("artifact.")) return "artifact";
  if (action.startsWith("engagement.")) return "engagement";
  if (action.startsWith("session.")) return "session";
  // Read tracking like "get./api/sources" — bucket by the path segment.
  if (action.startsWith("get.")) {
    if (action.includes("/audit") || action.includes("/admin")) return "other";
    if (action.includes("/library") || action.includes("/source")) return "source";
    if (action.includes("/artifact")) return "artifact";
    if (action.includes("/session") || action.includes("/engagement")) return "engagement";
  }
  return "other";
}

const KIND_TONE: Record<EventKind, string> = {
  auth: "border-argus-credible-border bg-argus-credible-bg text-argus-credible",
  source: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  artifact: "border-argus-web-border bg-argus-web-bg text-argus-web",
  engagement: "border-argus-border-moderate bg-elevated text-argus-secondary",
  session: "border-argus-border-moderate bg-elevated text-argus-secondary",
  other: "border-argus-border-subtle bg-surface text-argus-tertiary",
};

const KIND_LABEL: Record<EventKind, string> = {
  auth: "Auth",
  source: "Source",
  artifact: "Artifact",
  engagement: "Engagement",
  session: "Session",
  other: "Other",
};

function actorName(e: AuditEvent): string {
  const email = e.actor_email || "";
  if (!email) return "Someone";
  // demo@argus.local → "Demo User" (best-effort humanization)
  const local = email.split("@")[0] ?? "";
  if (!local) return email;
  const tokens = local.split(/[._-]+/).filter(Boolean);
  if (tokens.length === 0) return email;
  return tokens.map((t) => t[0]?.toUpperCase() + t.slice(1).toLowerCase()).join(" ");
}

function shortId(id: string | null | undefined): string {
  if (!id) return "";
  return id.length <= 8 ? id : `${id.slice(0, 8)}…`;
}

function pickStr(payload: Record<string, unknown>, ...keys: string[]): string {
  for (const k of keys) {
    const v = payload[k];
    if (typeof v === "string" && v) return v;
  }
  return "";
}

/**
 * Translate a raw audit event into a human-readable sentence.
 * Falls back to "{actor} did {action} on {resource}" for unknown shapes.
 */
function humanize(e: AuditEvent): string {
  const actor = actorName(e);
  const a = e.action;
  const p = e.payload || {};
  const filename = pickStr(p, "filename", "file_name");
  const title = pickStr(p, "title", "name");
  const url = pickStr(p, "url", "source_url");
  const trust = pickStr(p, "trust_level");
  const scope = pickStr(p, "scope");
  const role = pickStr(p, "role");
  const email = pickStr(p, "email");
  const target = filename || title || url || shortId(e.resource_id);

  switch (a) {
    case "auth.login":
      return `${actor} signed in.`;
    case "auth.logout":
      return `${actor} signed out.`;
    case "auth.register":
      return `${actor} created an account${email ? ` (${email})` : ""}.`;

    case "session.create":
    case "engagement.create":
      return `${actor} created engagement ${target ? `“${target}”` : shortId(e.resource_id)}.`;
    case "session.run":
    case "engagement.run_pipeline":
      return `${actor} kicked off the pipeline${target ? ` on “${target}”` : ""}.`;
    case "session.delete":
      return `${actor} deleted engagement ${target || shortId(e.resource_id)}.`;

    case "engagement.add_member":
      return `${actor} added ${email || "a member"}${role ? ` as ${role}` : ""}.`;
    case "engagement.remove_member":
      return `${actor} removed ${email || "a member"}.`;
    case "engagement.update_role":
      return `${actor} changed ${email || "a member"}’s role${role ? ` to ${role}` : ""}.`;

    case "source.upload":
    case "source.create":
      return `${actor} uploaded ${target ? `${target}` : "a source"}${trust ? ` (${trust.replace("_", " ")})` : ""}.`;
    case "source.url":
      return `${actor} added URL source ${url ? url : ""}.`;
    case "source.update":
    case "source.classify":
      if (scope === "firm") return `${actor} promoted ${target || "a source"} to firm-wide.`;
      if (trust) return `${actor} re-tagged ${target || "a source"} as ${trust.replace("_", " ")}.`;
      return `${actor} updated ${target || "a source"}.`;
    case "source.delete":
      return `${actor} deleted ${target || "a source"}.`;

    case "artifact.create":
      return `${actor} created ${title ? `memo “${title}”` : "an artifact"}.`;
    case "artifact.update":
      return `${actor} edited ${title ? `“${title}”` : "an artifact"}.`;
    case "artifact.export":
      return `${actor} exported ${title ? `“${title}”` : "an artifact"} as DOCX.`;
    case "artifact.delete":
      return `${actor} deleted ${title ? `“${title}”` : "an artifact"}.`;

    default: {
      // Read tracking: actions like "get./api/admin/audit" — collapse to "viewed X".
      if (a.startsWith("get.") || (e.method === "GET" && a.includes("/"))) {
        const path = e.path || "";
        if (path.includes("/audit")) return `${actor} viewed the audit log.`;
        if (path.includes("/library")) return `${actor} viewed the library.`;
        if (path.includes("/sessions")) return `${actor} viewed an engagement.`;
        return `${actor} viewed ${e.resource_type || "a page"}.`;
      }
      const verb = a.split(".").slice(-1)[0] || a;
      const noun = e.resource_type || "resource";
      return `${actor} ${verb.replace(/_/g, " ")} ${noun}${target ? ` ${target}` : ""}.`;
    }
  }
}

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function fmtDayHeading(iso: string | null): string {
  if (!iso) return "Unknown date";
  try {
    const d = new Date(iso);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    const sameDay = (a: Date, b: Date) =>
      a.getFullYear() === b.getFullYear() &&
      a.getMonth() === b.getMonth() &&
      a.getDate() === b.getDate();
    if (sameDay(d, today)) return "Today";
    if (sameDay(d, yesterday)) return "Yesterday";
    return d.toLocaleDateString(undefined, {
      weekday: "long",
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso.slice(0, 10);
  }
}

function dayKey(iso: string | null): string {
  if (!iso) return "unknown";
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return iso.slice(0, 10);
  }
}

export default function AuditPage() {
  return (
    <Suspense fallback={null}>
      <AuditInner />
    </Suspense>
  );
}

function AuditInner() {
  const params = useSearchParams();
  const engagementId = params.get("engagement_id");
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kindFilter, setKindFilter] = useState<"all" | EventKind>("all");
  const [actorFilter, setActorFilter] = useState<string>("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const url = engagementId
          ? `${BASE_URL}/api/admin/audit?engagement_id=${encodeURIComponent(engagementId)}&limit=200`
          : `${BASE_URL}/api/admin/audit?limit=200`;
        const res = await fetch(url, { credentials: "include", cache: "no-store" });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error((body as { detail?: string }).detail || `HTTP ${res.status}`);
        }
        const data = (await res.json()) as { events: AuditEvent[] };
        if (alive) setEvents(data.events);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "Failed to load audit log");
      }
    })();
    return () => {
      alive = false;
    };
  }, [engagementId]);

  const kindCounts = useMemo(() => {
    const c: Record<EventKind, number> = {
      auth: 0,
      source: 0,
      artifact: 0,
      engagement: 0,
      session: 0,
      other: 0,
    };
    for (const e of events ?? []) c[kindOf(e.action)] += 1;
    return c;
  }, [events]);

  const actors = useMemo(() => {
    const set = new Set<string>();
    for (const e of events ?? []) if (e.actor_email) set.add(e.actor_email);
    return Array.from(set).sort();
  }, [events]);

  const visible = useMemo(() => {
    if (!events) return [];
    const q = query.trim().toLowerCase();
    return events.filter((e) => {
      if (kindFilter !== "all" && kindOf(e.action) !== kindFilter) return false;
      if (actorFilter !== "all" && e.actor_email !== actorFilter) return false;
      if (!q) return true;
      const sentence = humanize(e).toLowerCase();
      return (
        sentence.includes(q) ||
        e.action.toLowerCase().includes(q) ||
        (e.actor_email || "").toLowerCase().includes(q)
      );
    });
  }, [events, kindFilter, actorFilter, query]);

  const grouped = useMemo(() => {
    const map = new Map<string, AuditEvent[]>();
    for (const e of visible) {
      const k = dayKey(e.created_at);
      const arr = map.get(k);
      if (arr) arr.push(e);
      else map.set(k, [e]);
    }
    // Sort keys descending (most recent day first)
    return Array.from(map.entries()).sort((a, b) => (a[0] < b[0] ? 1 : -1));
  }, [visible]);

  return (
    <main className="mx-auto max-w-[1100px] px-8 py-8">
      <header className="mb-6">
        <h1 className="font-serif text-[28px] font-semibold text-argus-primary">Audit log</h1>
        <p className="mt-1 text-[13px] text-argus-tertiary">
          {engagementId
            ? `Append-only audit trail for engagement ${engagementId.slice(0, 8)}…`
            : "Firm-wide audit trail (last 200 events)."}{" "}
          Lead-only on engagement view; firm admin on global view.
        </p>
      </header>

      {/* Toolbar */}
      {events && events.length > 0 ? (
        <div className="mb-4 space-y-2">
          <div className="flex items-center gap-2">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search who did what…"
              className="w-full max-w-sm rounded-sm border border-argus-border-moderate bg-surface px-3 py-1.5 text-[13px] placeholder:text-argus-quaternary focus:border-argus-border-strong focus:outline-none"
            />
            <span className="font-mono text-[11px] tabular-nums text-argus-tertiary">
              {visible.length} / {events.length}
            </span>
          </div>

          {/* Kind chips */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="argus-label mr-1">Kind</span>
            <FilterChip
              active={kindFilter === "all"}
              onClick={() => setKindFilter("all")}
              count={events.length}
            >
              All
            </FilterChip>
            {(Object.keys(KIND_LABEL) as EventKind[])
              .filter((k) => kindCounts[k] > 0)
              .map((k) => (
                <FilterChip
                  key={k}
                  active={kindFilter === k}
                  onClick={() => setKindFilter(k)}
                  count={kindCounts[k]}
                >
                  {KIND_LABEL[k]}
                </FilterChip>
              ))}
          </div>

          {/* Actor selector */}
          {actors.length > 1 ? (
            <div className="flex items-center gap-2 text-[11px]">
              <span className="argus-label mr-1">Actor</span>
              <select
                value={actorFilter}
                onChange={(e) => setActorFilter(e.target.value)}
                className="rounded-sm border border-argus-border-subtle bg-surface px-2 py-0.5 text-[11px] focus:border-argus-border-strong focus:outline-none"
              >
                <option value="all">All</option>
                {actors.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <div className="rounded-argus-md border border-argus-contested-border bg-argus-contested-bg px-4 py-3 text-[13px] text-argus-contested">
          {error}
        </div>
      ) : !events ? (
        <p className="text-[13px] text-argus-tertiary">Loading…</p>
      ) : events.length === 0 ? (
        <EmptyState
          title="No events yet."
          body="Activity will appear here once people start using the workspace."
        />
      ) : visible.length === 0 ? (
        <EmptyState
          title="No events match these filters."
          cta={
            <button
              type="button"
              onClick={() => {
                setQuery("");
                setKindFilter("all");
                setActorFilter("all");
              }}
              className="text-[12px] text-argus-accent hover:underline"
            >
              Clear filters
            </button>
          }
        />
      ) : (
        <div className="space-y-6">
          {grouped.map(([key, items]) => (
            <section key={key}>
              <h2 className="argus-label mb-2 flex items-baseline justify-between">
                <span>{fmtDayHeading(items[0]?.created_at ?? null)}</span>
                <span className="font-mono tabular-nums normal-case tracking-normal text-argus-tertiary">
                  {items.length}
                </span>
              </h2>
              <ul className="overflow-hidden rounded-sm border border-argus-border-subtle bg-surface">
                {items.map((e) => {
                  const kind = kindOf(e.action);
                  return (
                    <li
                      key={e.id}
                      className="grid grid-cols-[max-content_max-content_1fr_max-content] items-center gap-3 border-b border-argus-border-subtle/60 px-3 py-2 text-[12px] last:border-b-0 hover:bg-elevated"
                    >
                      <span className="font-mono tabular-nums text-argus-tertiary">
                        {fmtTime(e.created_at)}
                      </span>
                      <span
                        className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${KIND_TONE[kind]}`}
                      >
                        {KIND_LABEL[kind]}
                      </span>
                      <span className="min-w-0 leading-snug text-argus-primary">
                        {humanize(e)}
                      </span>
                      <span
                        className="truncate font-mono text-[10px] text-argus-tertiary"
                        title={`${e.method ?? ""} ${e.path ?? ""} · ${e.action}`}
                      >
                        {e.action}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}
    </main>
  );
}

function FilterChip({
  active,
  onClick,
  children,
  count,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-sm border px-2 py-1 text-[11px] transition-colors ${
        active
          ? "border-argus-primary bg-argus-primary text-argus-inverse"
          : "border-argus-border-subtle bg-surface text-argus-secondary hover:border-argus-border-moderate hover:text-argus-primary"
      }`}
    >
      <span>{children}</span>
      {count !== undefined ? (
        <span
          className={`font-mono text-[10px] tabular-nums ${
            active ? "opacity-80" : "text-argus-tertiary"
          }`}
        >
          {count}
        </span>
      ) : null}
    </button>
  );
}
