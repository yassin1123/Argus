import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type BadgeVariant = "success" | "warning" | "danger" | "neutral" | "info";

export function Badge({
  children,
  variant = "neutral",
  className = "",
}: {
  children: ReactNode;
  variant?: BadgeVariant;
  className?: string;
}) {
  const styles: Record<BadgeVariant, string> = {
    success: "bg-argus-success-subtle text-argus-success border-argus-success-border",
    warning: "bg-argus-warning-subtle text-argus-warning border-argus-warning-border",
    danger: "bg-argus-danger-subtle text-argus-danger border-argus-danger-border",
    neutral: "bg-argus-neutral-subtle text-argus-neutral border-argus-border-subtle",
    info: "bg-argus-info-subtle text-argus-accent border-argus-info-border",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em]",
        styles[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
