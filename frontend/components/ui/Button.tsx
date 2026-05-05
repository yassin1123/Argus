import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type Variant = "primary" | "ghost" | "outline";

export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: Variant;
}) {
  const base =
    "inline-flex items-center justify-center rounded-argus px-5 text-sm font-semibold transition-colors duration-150 disabled:pointer-events-none";
  const styles: Record<Variant, string> = {
    primary:
      "bg-ink text-white hover:bg-ink-muted h-10 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-argus-accent",
    ghost:
      "h-9 bg-transparent text-argus-secondary hover:bg-elevated hover:text-argus-primary border border-transparent",
    outline:
      "h-9 border border-argus-border-subtle bg-transparent text-argus-primary hover:border-argus-border-moderate hover:bg-elevated",
  };
  return (
    <button type="button" className={cn(base, styles[variant], className)} {...props}>
      {children}
    </button>
  );
}
