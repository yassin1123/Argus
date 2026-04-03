import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Surface({
  children,
  className = "",
  elevated = false,
}: {
  children: ReactNode;
  className?: string;
  elevated?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-argus-md border border-argus-border-subtle bg-elevated transition-[box-shadow] duration-150",
        elevated && "shadow-argus-sm",
        className
      )}
    >
      {children}
    </div>
  );
}
