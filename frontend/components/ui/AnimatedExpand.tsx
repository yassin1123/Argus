"use client";

import type { ReactNode } from "react";

export function AnimatedExpand({
  show,
  children,
  className = "",
}: {
  show: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`grid transition-[grid-template-rows] duration-200 ease-in-out ${
        show ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
      } ${className}`}
    >
      <div className="overflow-hidden">{children}</div>
    </div>
  );
}
