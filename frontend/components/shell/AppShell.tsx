"use client";

import { usePathname } from "next/navigation";

import { ToastProvider } from "@/components/ui/Toast";
import LeftRail from "./LeftRail";

const NO_CHROME_PATHS = ["/login", "/register"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const hideChrome = NO_CHROME_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  if (hideChrome) {
    return <ToastProvider>{children}</ToastProvider>;
  }

  return (
    <ToastProvider>
      <div className="argus-shell">
        <LeftRail />
        <div className="min-w-0">{children}</div>
      </div>
    </ToastProvider>
  );
}
