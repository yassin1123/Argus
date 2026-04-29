"use client";

export type WorkspaceTab = "path" | "answer" | "graph" | "audit" | "sources";

const TABS: { id: WorkspaceTab; label: string }[] = [
  { id: "path", label: "Decision path" },
  { id: "answer", label: "Answer" },
  { id: "graph", label: "Graph" },
  { id: "audit", label: "Audit" },
  { id: "sources", label: "Sources" },
];

export default function WorkspaceTabs({
  active,
  onChange,
  evidenceCount,
  graphAvailable,
}: {
  active: WorkspaceTab;
  onChange: (tab: WorkspaceTab) => void;
  evidenceCount: number;
  graphAvailable: boolean;
}) {
  return (
    <nav
      role="tablist"
      aria-label="Workspace views"
      className="mb-4 flex items-center gap-1 border-b border-argus-border-subtle"
    >
      {TABS.map((t) => {
        const isActive = active === t.id;
        const disabled =
          (t.id === "graph" && !graphAvailable) ||
          (t.id === "path" && !graphAvailable) ||
          (t.id === "sources" && evidenceCount === 0);
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            disabled={disabled}
            onClick={() => onChange(t.id)}
            className={[
              "relative -mb-px px-3 py-2 text-[13px] transition-colors",
              isActive
                ? "border-b-2 border-argus-accent font-medium text-argus-primary"
                : "border-b-2 border-transparent text-argus-tertiary hover:text-argus-secondary",
              disabled ? "cursor-not-allowed opacity-40" : "",
            ].join(" ")}
          >
            {t.label}
            {t.id === "sources" && evidenceCount > 0 ? (
              <span className="ml-1.5 inline-block rounded-argus-sm bg-argus-neutral-subtle px-1.5 py-0.5 text-[10px] text-argus-secondary">
                {evidenceCount}
              </span>
            ) : null}
          </button>
        );
      })}
    </nav>
  );
}
