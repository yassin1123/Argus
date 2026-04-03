import { sanitizeUserFacingText } from "@/lib/formatters";

export function FindingCard({ index, text }: { index: number; text: string }) {
  const n = String(index + 1).padStart(2, "0");
  const clean = sanitizeUserFacingText(text);
  return (
    <div className="group relative mb-3 rounded-[14px] border border-argus-border-subtle bg-surface px-6 py-5 shadow-argus-sm transition-shadow duration-150 hover:shadow-argus">
      <div className="absolute inset-y-0 left-0 w-[3px] rounded-l-[14px] bg-argus-success" aria-hidden />
      <span className="font-mono text-[11px] text-argus-tertiary">{n}</span>
      <p className="mt-2 text-sm leading-[1.65] text-argus-primary">{clean}</p>
    </div>
  );
}
