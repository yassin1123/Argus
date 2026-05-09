"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { getCurrentUser, logout, type AuthUser } from "@/lib/api";

type NavItem = {
  href: string;
  label: string;
  match: (path: string) => boolean;
  icon: React.ReactNode;
};

function HomeIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-7H10v7H4a1 1 0 0 1-1-1z" />
    </svg>
  );
}
function LibraryIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M4 5h4v14H4zM10 5h4v14h-4zM18 5l3 14-4 1L14 6z" />
    </svg>
  );
}
function FirmLibraryIcon() {
  // Open book with a tag tucked in — distinguishes "firm-curated" from the
  // legacy promoted-sources library glyph.
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M3 5a2 2 0 0 1 2-2h6v18H5a2 2 0 0 1-2-2zM21 5a2 2 0 0 0-2-2h-6v18h6a2 2 0 0 0 2-2z" />
      <path d="M11 7h2M11 11h2" />
    </svg>
  );
}
function VaultIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <rect x="3" y="3" width="18" height="18" rx="1" />
      <circle cx="12" cy="12" r="3.5" />
      <path d="M12 5v2M12 17v2M19 12h2M3 12h2" />
    </svg>
  );
}
function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <path d="M6 9a6 6 0 0 1 12 0c0 7 3 8 3 8H3s3-1 3-8" />
      <path d="M10.5 21a2 2 0 0 0 3.5-1" />
    </svg>
  );
}
function GearIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9c.3.6.9 1 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  );
}

const NAV: NavItem[] = [
  { href: "/", label: "Engagements", match: (p) => p === "/" || p.startsWith("/sessions"), icon: <HomeIcon /> },
  // /library = legacy promoted-sources list (sources promoted to firm scope
  // from individual engagement uploads). Renamed to "Sources" so the new
  // /firm/library upload route can claim the "Firm Library" label.
  { href: "/library", label: "Sources", match: (p) => p === "/library" || p.startsWith("/library/"), icon: <LibraryIcon /> },
  // /firm/library = new firm-curated content (Phase 2 / Week 5 / Day 2 ).
  { href: "/firm/library", label: "Firm Library", match: (p) => p.startsWith("/firm/library"), icon: <FirmLibraryIcon /> },
  { href: "/vault", label: "Knowledge Vault", match: (p) => p.startsWith("/vault"), icon: <VaultIcon /> },
  { href: "/notifications", label: "Notifications", match: (p) => p.startsWith("/notifications"), icon: <BellIcon /> },
  { href: "/settings", label: "Settings", match: (p) => p.startsWith("/settings"), icon: <GearIcon /> },
];

export default function LeftRail() {
  const pathname = usePathname() || "/";

  return (
    <aside
      aria-label="Primary navigation"
      className="flex flex-col items-center border-r border-argus-border-subtle bg-[var(--bg-rail)] py-3"
      style={{ width: "var(--rail-nav)" }}
    >
      <Link
        href="/"
        className="mb-4 flex h-9 w-9 items-center justify-center rounded-sm font-serif text-[18px] font-semibold text-argus-primary"
        title="Argus"
      >
        A
      </Link>

      <nav className="flex flex-1 flex-col items-center gap-1">
        {NAV.map((item) => {
          const active = item.match(pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              aria-label={item.label}
              aria-current={active ? "page" : undefined}
              className={`group relative flex h-10 w-10 items-center justify-center rounded-sm transition-colors ${
                active
                  ? "bg-argus-primary text-argus-inverse"
                  : "text-argus-secondary hover:bg-elevated hover:text-argus-primary"
              }`}
            >
              {item.icon}
              {active ? (
                <span
                  aria-hidden
                  className="absolute -left-3 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full bg-argus-accent"
                />
              ) : null}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col items-center gap-2 border-t border-argus-border-subtle pt-3">
        <AccountMenu />
      </div>
    </aside>
  );
}

function AccountMenu() {
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const u = await getCurrentUser();
      if (alive) setUser(u);
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const initials = (user?.full_name || user?.email || "?")
    .split(/\s+|@/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("") || "?";

  const handleLogout = async () => {
    await logout();
    router.replace("/login");
    router.refresh();
  };

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={user ? `${user.full_name || user.email}` : "Account"}
        aria-label="Account menu"
        className="flex h-8 w-8 items-center justify-center rounded-full bg-argus-primary text-[10px] font-semibold text-argus-inverse hover:opacity-90"
      >
        {initials}
      </button>
      {open ? (
        <div className="absolute bottom-0 left-12 z-50 w-56 rounded-argus-md border border-argus-border-moderate bg-surface p-3 shadow-popover">
          <div className="border-b border-argus-border-subtle pb-2">
            <div className="font-serif text-[13px] font-semibold text-argus-primary">
              {user?.full_name || "Not signed in"}
            </div>
            <div className="text-[11px] text-argus-tertiary">{user?.email || "—"}</div>
          </div>
          <div className="mt-2 flex flex-col gap-0.5 text-[12px]">
            <Link
              href="/settings"
              onClick={() => setOpen(false)}
              className="rounded-sm px-2 py-1 text-argus-secondary hover:bg-elevated hover:text-argus-primary"
            >
              Settings
            </Link>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-sm px-2 py-1 text-left text-argus-secondary hover:bg-elevated hover:text-argus-primary"
            >
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
