import type { EvidenceObjectRow } from "@/lib/types";

function qualityLabel(score: number | undefined): string {
  if (score == null) return "";
  if (score >= 0.55) return "Strong source";
  if (score >= 0.3) return "Moderate";
  return "Weak";
}

function ConfidencePips({ level }: { level: string }) {
  const l = level.toLowerCase();
  const high = l === "high";
  const med = l === "medium";
  const low = l === "low";
  const fillSuccess = "bg-argus-success";
  const fillWarn = "bg-argus-warning";
  const fillDanger = "bg-argus-danger";
  const empty = "bg-argus-border-moderate/40";

  let a = empty;
  let b = empty;
  let c = empty;
  if (high) {
    a = b = c = fillSuccess;
  } else if (med) {
    a = b = fillWarn;
  } else if (low) {
    a = fillDanger;
  } else {
    a = b = fillWarn;
  }

  return (
    <div className="flex gap-0.5" aria-hidden>
      <span className={`h-1.5 w-1.5 rounded-full ${a}`} />
      <span className={`h-1.5 w-1.5 rounded-full ${b}`} />
      <span className={`h-1.5 w-1.5 rounded-full ${c}`} />
    </div>
  );
}

function SourceTypeBadge({ type }: { type: string }) {
  const t = type.toLowerCase();
  let cls = "bg-argus-neutral-subtle text-argus-secondary";
  if (t === "web") cls = "bg-argus-info-subtle text-argus-accent";
  if (t === "document") cls = "bg-argus-neutral-subtle text-argus-neutral";
  if (t === "inference" || t === "inferred") cls = "bg-argus-warning-subtle text-argus-warning";
  const label = t === "document" ? "Document" : t === "web" ? "Web" : "Inferred";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${cls}`}>{label}</span>
  );
}

export function EvidenceCard({ o }: { o: EvidenceObjectRow }) {
  const url = o.source_url?.trim();
  const ql = qualityLabel(o.source_score);

  return (
    <div className="mb-2 rounded-[12px] border border-argus-border-subtle bg-surface p-3.5 shadow-[0_1px_3px_rgba(10,10,15,0.05)]">
      <div className="mb-2 flex items-start justify-between gap-2">
        {url ? (
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="line-clamp-1 text-xs font-semibold text-argus-primary transition-colors duration-150 hover:text-argus-accent"
          >
            {o.source_title || "Source"}
          </a>
        ) : (
          <span className="line-clamp-1 text-xs font-semibold text-argus-primary">
            {o.source_title || "Source"}
          </span>
        )}
        <SourceTypeBadge type={o.is_inference ? "inferred" : o.source_type || "document"} />
      </div>
      <p className="line-clamp-2 text-[11px] italic leading-[1.5] text-argus-tertiary">
        {o.quote || o.claim || "—"}
      </p>
      <div className="mt-2.5 flex items-center justify-between">
        <ConfidencePips level={o.confidence || "medium"} />
        {ql ? <span className="text-[10px] text-argus-tertiary">{ql}</span> : null}
      </div>
    </div>
  );
}
