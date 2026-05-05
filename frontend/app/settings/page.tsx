"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useToast } from "@/components/ui/Toast";
import { getCurrentUser, logout, type AuthUser } from "@/lib/api";

function initialsOf(u: AuthUser | null): string {
  const src = (u?.full_name || u?.email || "?")
    .split(/\s+|@/)
    .filter(Boolean)
    .slice(0, 2);
  const out = src.map((p) => p[0]?.toUpperCase() ?? "").join("");
  return out || "?";
}

function roleLabel(role: string | undefined): string {
  if (!role) return "Member";
  if (role === "admin") return "Firm admin";
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export default function SettingsPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [signingOut, setSigningOut] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const u = await getCurrentUser();
        if (alive) setUser(u);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const handleSignOut = async () => {
    setSigningOut(true);
    try {
      await logout();
      router.replace("/login");
      router.refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Sign-out failed", { variant: "error" });
      setSigningOut(false);
    }
  };

  return (
    <main className="mx-auto max-w-[800px] px-8 py-12">
      <header className="mb-6">
        <h1 className="font-serif text-[28px] font-semibold text-argus-primary">Settings</h1>
        <p className="mt-1 text-[13px] text-argus-tertiary">
          Profile, model orchestration, and integrations.
        </p>
      </header>

      {/* Profile */}
      <section className="mb-6 border border-argus-border-subtle bg-surface p-5">
        <h2 className="argus-label mb-3">Profile</h2>
        {loading ? (
          <p className="text-[12px] text-argus-tertiary">Loading…</p>
        ) : !user ? (
          <p className="text-[12px] text-argus-tertiary">Not signed in.</p>
        ) : (
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-argus-primary text-[14px] font-semibold text-argus-inverse">
              {initialsOf(user)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-serif text-[15px] font-semibold text-argus-primary">
                {user.full_name || "(no name set)"}
              </div>
              <div className="text-[12px] text-argus-tertiary">{user.email}</div>
              <div className="mt-2 flex items-center gap-2">
                <span
                  className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                    user.role === "admin"
                      ? "border-argus-firm-border bg-argus-firm-bg text-argus-firm"
                      : "border-argus-border-subtle bg-elevated text-argus-tertiary"
                  }`}
                >
                  {roleLabel(user.role)}
                </span>
                <span className="font-mono text-[10px] text-argus-tertiary">
                  id {user.user_id.slice(0, 8)}…
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void handleSignOut()}
              disabled={signingOut}
              className="rounded-sm border border-argus-border-moderate bg-surface px-3 py-1.5 text-[12px] font-medium text-argus-secondary hover:border-argus-contested hover:text-argus-contested disabled:opacity-50"
            >
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </div>
        )}
      </section>

      {/* Model orchestration */}
      <section className="mb-6 border border-argus-border-subtle bg-surface p-5">
        <h2 className="argus-label mb-3">Model orchestration</h2>
        <ul className="space-y-2 text-[13px]">
          {[
            { name: "Claude (Anthropic)", role: "Long-context synthesis, critique", status: "Active" },
            { name: "GPT-4 (OpenAI)", role: "Default analyst, planner, writer", status: "Active" },
            { name: "Gemini (Google)", role: "Cross-checking, multimodal", status: "Standby" },
            { name: "Grok (xAI)", role: "Adversarial second opinion", status: "Standby" },
          ].map((m) => {
            const active = m.status === "Active";
            return (
              <li
                key={m.name}
                className="flex items-center justify-between border-b border-argus-border-subtle py-2 last:border-b-0"
              >
                <div>
                  <div className="font-serif text-[14px] text-argus-primary">{m.name}</div>
                  <div className="text-[11px] text-argus-tertiary">{m.role}</div>
                </div>
                <span
                  className={`rounded-sm border px-1.5 py-0.5 text-[10px] uppercase tracking-wide ${
                    active
                      ? "border-argus-firm-border bg-argus-firm-bg text-argus-firm"
                      : "border-argus-border-subtle bg-elevated text-argus-tertiary"
                  }`}
                >
                  {m.status}
                </span>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="border border-argus-border-subtle bg-surface p-5">
        <h2 className="argus-label mb-3">Integrations</h2>
        <p className="text-[13px] text-argus-tertiary">
          Snowflake · S&amp;P Capital IQ · SharePoint · Slack · Linear · Custom API. None connected.
        </p>
      </section>
    </main>
  );
}
