export default function Loading() {
  return (
    <>
      <header className="argus-topbar">
        <span className="text-[11px] text-argus-tertiary">Loading engagement…</span>
      </header>
      <div className="argus-workbench">
        <div className="argus-pane-source" />
        <div className="argus-pane-center" />
        <div className="argus-pane-artifacts" />
      </div>
    </>
  );
}
