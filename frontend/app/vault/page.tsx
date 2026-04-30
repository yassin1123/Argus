export default function VaultPage() {
  return (
    <main className="mx-auto max-w-[900px] px-8 py-12">
      <header className="mb-6">
        <h1 className="font-serif text-[28px] font-semibold text-argus-primary">Knowledge Vault</h1>
        <p className="mt-1 text-[13px] text-argus-tertiary">
          Cross-engagement learnings. When a question maps to one Argus has answered before, the Vault surfaces it (subject to permissions).
        </p>
      </header>
      <div className="rounded-argus-md border border-dashed border-argus-border-moderate p-10 text-center">
        <p className="font-serif text-[16px] text-argus-primary">Institutional memory in progress.</p>
        <p className="mt-1 text-[12px] text-argus-tertiary">
          The Vault aggregates resolved engagements into a searchable index. Coming once at least 5 engagements have been completed.
        </p>
      </div>
    </main>
  );
}
