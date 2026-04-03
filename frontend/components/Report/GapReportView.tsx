"use client";

export interface GapReport {
  title?: string;
  missing_evidence?: string[];
  suggested_searches?: string[];
  contradictions?: string[];
  notes?: string;
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
      <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export default function GapReportView({ gap }: { gap: GapReport }) {
  const missing = gap.missing_evidence ?? [];
  const searches = gap.suggested_searches ?? [];
  const contra = gap.contradictions ?? [];

  return (
    <section className="rounded-[20px] border border-argus-warning-border bg-[#FFFBF0] p-8">
      <div className="mb-4 flex items-center gap-3">
        <div className="rounded-full bg-argus-warning-subtle p-2">
          <SearchIcon className="text-argus-warning" />
        </div>
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-argus-warning">
          Evidence gate
        </span>
      </div>
      <h2 className="font-serif text-xl text-argus-primary">
        {gap.title ?? "Not enough evidence to recommend"}
      </h2>
      <p className="mt-3 text-sm leading-[1.65] text-argus-secondary">
        {gap.notes ??
          "Argus could not ground a confident recommendation. Add documents or refine the question, then run again."}
      </p>

      {missing.length > 0 && (
        <div className="mt-5">
          <p className="mb-2 text-xs font-semibold text-argus-warning">What was missing</p>
          <ul className="space-y-1.5">
            {missing.map((m, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-argus-secondary">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-argus-warning-border" />
                {m}
              </li>
            ))}
          </ul>
        </div>
      )}

      {searches.length > 0 && (
        <div className="mt-6">
          <p className="mb-2 text-xs font-semibold text-argus-secondary">Suggested searches</p>
          <ul className="space-y-1.5">
            {searches.map((s, i) => (
              <li key={i} className="text-sm text-argus-secondary">
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {contra.length > 0 && (
        <div className="mt-6">
          <p className="mb-2 text-xs font-semibold text-argus-secondary">Tensions noted</p>
          <ul className="space-y-1.5">
            {contra.map((c, i) => (
              <li key={i} className="text-sm text-argus-secondary">
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
