"use client";

import { useEffect, useState } from "react";

import LibraryBrowse from "@/components/FirmLibrary/LibraryBrowse";
import LibraryDetailPanel from "@/components/FirmLibrary/LibraryDetailPanel";
import UploadPanel from "@/components/FirmLibrary/UploadPanel";
import { getCurrentUser, type AuthUser } from "@/lib/api";
import type { FirmContent } from "@/lib/api/firmLibrary";

// Firm Library page — Day 3 wires upload (admin-only) + browse + detail.
// Cross-firm isolation is enforced server-side; this page just respects
// the current user's `default_firm_role` to render the right UI.
export default function FirmLibraryPage() {
  const [user, setUser] = useState<AuthUser | null | "loading">("loading");
  const [refreshKey, setRefreshKey] = useState(0);
  const [openContent, setOpenContent] = useState<FirmContent | null>(null);

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

  if (user === "loading") {
    return (
      <main className="mx-auto max-w-[1100px] px-8 py-8">
        <p className="text-[13px] text-argus-tertiary">Loading…</p>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto max-w-[1100px] px-8 py-8">
        <p className="text-[13px] text-argus-contested">Sign in required.</p>
      </main>
    );
  }

  if (!user.default_firm_id) {
    return (
      <main className="mx-auto max-w-[1100px] px-8 py-8">
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

  const isAdmin = user.default_firm_role === "admin";

  const onUploaded = (_content: FirmContent) => {
    setRefreshKey((k) => k + 1);
  };

  const onMutated = (_next: FirmContent) => {
    setRefreshKey((k) => k + 1);
  };

  return (
    <main className="mx-auto max-w-[1100px] px-8 py-8">
      <header className="mb-6 flex items-start justify-between gap-3">
        <div>
          <h1 className="font-serif text-[28px] font-semibold text-argus-primary">
            Firm Library
          </h1>
          <p className="mt-1 text-[13px] text-argus-tertiary">
            Firm-curated content — playbooks, sector primers, prior reports,
            frameworks. Visible to every engagement at your firm and never
            leaked across firms.
          </p>
        </div>
        <span
          className={`rounded-sm border px-2 py-0.5 text-[10px] uppercase tracking-wide ${
            isAdmin
              ? "border-argus-firm-border bg-argus-firm-bg text-argus-firm"
              : "border-argus-border-subtle bg-elevated text-argus-tertiary"
          }`}
          data-testid="firm-role-badge"
        >
          {isAdmin ? "Firm admin" : "Member"}
        </span>
      </header>

      {isAdmin ? (
        <section className="mb-6" data-testid="firm-library-upload-section">
          <UploadPanel firmId={user.default_firm_id} onUploaded={onUploaded} />
        </section>
      ) : (
        <section className="mb-6 rounded-argus-md border border-dashed border-argus-border-moderate p-4 text-center text-[12px] text-argus-tertiary">
          Uploading and editing library content is admin-only. Ask a firm
          admin if you have content to add.
        </section>
      )}

      <section>
        <h2 className="argus-label mb-3">Browse</h2>
        <LibraryBrowse
          firmId={user.default_firm_id}
          refreshKey={refreshKey}
          onSelect={setOpenContent}
        />
      </section>

      {openContent ? (
        <LibraryDetailPanel
          firmId={user.default_firm_id}
          contentId={openContent.id}
          isAdmin={isAdmin}
          onClose={() => setOpenContent(null)}
          onMutated={onMutated}
        />
      ) : null}
    </main>
  );
}
