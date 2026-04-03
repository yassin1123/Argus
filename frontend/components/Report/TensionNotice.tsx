function TriangleAlert({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function TensionNotice({ severity }: { severity: number }) {
  return (
    <div className="mb-4 flex items-start gap-3 rounded-[12px] border border-argus-warning-border bg-argus-warning-subtle px-4 py-3.5">
      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-argus-warning" />
      <div>
        <p className="text-xs font-semibold text-argus-warning">Evidence tensions detected</p>
        <p className="mt-0.5 text-xs text-argus-tertiary">
          Severity {severity}. This report&apos;s confidence may reflect contested evidence. Review the
          evidence panel for details.
        </p>
      </div>
    </div>
  );
}
