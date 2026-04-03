export function NextStepRow({ n, text }: { n: number; text: string }) {
  return (
    <div className="flex items-start gap-4 border-b border-argus-border-subtle py-3 last:border-0">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-bold text-white">
        {n}
      </div>
      <p className="pt-0.5 text-sm leading-[1.65] text-argus-primary">{text}</p>
    </div>
  );
}
