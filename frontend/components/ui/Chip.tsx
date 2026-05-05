"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Chip({
  children,
  active,
  onClick,
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
}) {
  const Tag = onClick ? "button" : "span";
  return (
    <Tag
      type={onClick ? "button" : undefined}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-medium transition-colors duration-150",
        active
          ? "border-argus-border-strong bg-argus-info-subtle text-argus-accent"
          : "border-argus-border-subtle text-argus-secondary hover:border-argus-border-moderate hover:text-argus-primary",
        onClick && "cursor-pointer"
      )}
    >
      {children}
    </Tag>
  );
}
