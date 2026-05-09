"use client";

import { useEffect, useState } from "react";

import UploadPanel from "@/components/FirmLibrary/UploadPanel";
import { getCurrentUser, type AuthUser } from "@/lib/api";
import type { FirmContent } from "@/lib/api/firmLibrary";

// Firm Library upload page (Phase 2 / Week 5 / Day 2 ).
// Day 2 is upload-only. Browse + retire come Day 3 — the same page will
// gain a list view below the panel that reads /api/firms/{id}/library.
export default function FirmLibraryPage() {
  const [user, setUser] = useState<AuthUser | null | "loading">("loading");
  const [recentlyAdded, setRecentlyAdded] = useState<FirmContent[]>([]);

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

  const onUploaded = (content: FirmContent) => {
    setRecentlyAdded((prev) => {
      // Dedupe by id (re-upload of an idempotent file returns the same id).
      const filtered = prev.filter((p) => p.id !== content.id);
      return [content, ...filtered].slice(0, 5);
    });
  };

  if (user === "loading") {
    return (
      <main className="mx-auto max-w-[800px] px-8 py-8">
        <p className="text-[13px] text-argus-tertiary">Loading…</p>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto max-w-[800px] px-8 py-8">
        <p className="text-[13px] text-argus-contested">
          Sign in required.
        </p>
      </main>
    );
  }

  if (!user.default_firm_id) {
    return (
      <main className="mx-auto max-w-[800px] px-8 py-8">
        <h1 className="font-serif text-[28px] font-semibold text-argus-primary">
          Firm Library
        </h1>
        <p className="mt-2 rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested">
          Your account isn&apos;t associated with a firm yet. Ask an admin to
          add you to a firm before uploading.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-[800px] px-8 py-8">
      <header className="mb-6">
        <h1 className="font-serif text-[28px] font-semibold text-argus-primary">
          Firm Library
        </h1>
        <p className="mt-1 text-[13px] text-argus-tertiary">
          Add firm-curated content — playbooks, sector primers, prior reports,
          frameworks. Uploaded content is chunked, embedded, and made available
          to every engagement at your firm. Browse + retire arrive in the next
          release.
        </p>
      </header>

      <UploadPanel firmId={user.default_firm_id} onUploaded={onUploaded} />

      {recentlyAdded.length === 0 ? (
        <div className="mt-6 rounded-argus-md border border-dashed border-argus-border-moderate p-6 text-center">
          <p className="font-serif text-[15px] text-argus-primary">
            No content uploaded in this session yet.
          </p>
          <p className="mt-1 text-[12px] text-argus-tertiary">
            Drag a playbook, primer, or framework above to add it to your firm
            library.
          </p>
        </div>
      ) : (
        <section className="mt-6">
          <h2 className="argus-label mb-2">Just added</h2>
          <ul className="divide-y divide-argus-border-subtle rounded-argus-md border border-argus-border-subtle bg-surface">
            {recentlyAdded.map((c) => (
              <li
                key={c.id}
                className="flex items-center justify-between px-3 py-2 text-[12px]"
              >
                <div>
                  <div className="font-medium text-argus-primary">{c.title}</div>
                  <div className="text-[11px] text-argus-tertiary">
                    {c.category.replaceAll("_", " ")} ·{" "}
                    <span className="font-mono tabular-nums">
                      {c.chunk_count} chunks
                    </span>
                    {c.sector_tags.length > 0 ? (
                      <> · {c.sector_tags.join(", ")}</>
                    ) : null}
                  </div>
                </div>
                <span className="rounded-sm border border-argus-firm-border bg-argus-firm-bg px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-argus-firm">
                  {c.trust_level.replaceAll("_", " ")}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
