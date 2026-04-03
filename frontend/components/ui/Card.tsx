import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Card({
  children,
  className = "",
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-argus-lg border border-argus-border-subtle bg-surface shadow-argus-sm",
        className
      )}
    >
      <div className={padded ? "p-6 md:p-8" : ""}>{children}</div>
    </div>
  );
}
