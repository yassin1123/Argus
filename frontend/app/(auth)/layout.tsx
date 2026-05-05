export default function AuthLayout({ children }: { children: React.ReactNode }) {
  // Auth pages render full-bleed; bypass the workbench shell.
  return <div className="min-h-screen bg-canvas">{children}</div>;
}
