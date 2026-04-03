export function RiskCard({ text }: { text: string }) {
  return (
    <div className="group relative mb-3 rounded-[14px] border border-argus-border-subtle bg-surface px-6 py-5 shadow-argus-sm transition-shadow duration-150 hover:shadow-argus">
      <div className="absolute inset-y-0 left-0 w-[3px] rounded-l-[14px] bg-argus-warning" aria-hidden />
      <p className="text-sm leading-[1.65] text-argus-primary">{text}</p>
    </div>
  );
}
