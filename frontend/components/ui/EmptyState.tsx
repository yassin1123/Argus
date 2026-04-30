import type { ReactNode } from "react";

/**
 * Consistent empty-state block. Replaces the various dashed-border /
 * "No items yet" boxes scattered across the app with a single component.
 */
export default function EmptyState({
  icon,
  title,
  body,
  cta,
  className = "",
}: {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  cta?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-argus-md border border-dashed border-argus-border-moderate bg-surface px-6 py-10 text-center ${className}`}
    >
      {icon ? (
        <div className="mx-auto mb-3 flex h-9 w-9 items-center justify-center rounded-sm bg-elevated text-argus-tertiary">
          {icon}
        </div>
      ) : null}
      <p className="font-serif text-[16px] text-argus-primary">{title}</p>
      {body ? <div className="mx-auto mt-1 max-w-md text-[12px] leading-relaxed text-argus-tertiary">{body}</div> : null}
      {cta ? <div className="mt-4 flex justify-center">{cta}</div> : null}
    </div>
  );
}
