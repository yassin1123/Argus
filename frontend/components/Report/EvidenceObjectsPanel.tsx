"use client";

export interface EvidenceObjectRow {
  id: string;
  task_id?: number | null;
  claim?: string;
  quote?: string;
  source_title?: string;
  source_url?: string;
  source_type?: string;
  confidence?: string;
}

export default function EvidenceObjectsPanel({ items }: { items: EvidenceObjectRow[] }) {
  if (!items?.length) return null;
  return (
    <section className="mb-8 rounded-xl border border-gray-800 bg-gray-900/40 p-4">
      <h3 className="text-sm font-medium text-gray-400">Citeable evidence ({items.length})</h3>
      <ul className="mt-3 max-h-64 space-y-3 overflow-y-auto text-sm">
        {items.slice(0, 50).map((o) => (
          <li key={o.id} className="border-l-2 border-blue-600/50 pl-3 text-gray-300">
            <span className="text-xs text-gray-500">{o.id.slice(0, 8)}… · {o.source_type}</span>
            {o.source_title ? (
              <p className="font-medium text-gray-200">{o.source_title}</p>
            ) : null}
            <p className="mt-1 line-clamp-3 text-gray-400">{o.quote || o.claim}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
