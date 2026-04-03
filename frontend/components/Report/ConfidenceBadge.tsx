const STYLES: Record<string, string> = {
  High: "bg-argus-success-subtle text-argus-success border-argus-success-border",
  "Medium-High": "bg-argus-info-subtle text-argus-accent border-argus-info-border",
  Medium: "bg-argus-warning-subtle text-argus-warning border-argus-warning-border",
  Low: "bg-argus-danger-subtle text-argus-danger border-argus-danger-border",
};

export function ConfidenceBadge({ level }: { level: string }) {
  const cls = STYLES[level] ?? STYLES.Medium;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-[0.08em] ${cls}`}
    >
      {level} confidence
    </span>
  );
}
