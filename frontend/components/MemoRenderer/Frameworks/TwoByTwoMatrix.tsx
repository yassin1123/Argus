"use client";

/**
 * 2x2 matrix renderer — W8/D3.
 *
 * CSS-grid 4-cell layout with axes labeled along the bottom and the
 * left edge. Each item sits inside its assigned quadrant (top_left,
 * top_right, bottom_left, bottom_right). Clicking an item opens a
 * detail panel showing the full rationale + evidence citations.
 *
 * Functional, not fancy — per W8/D3 hard rule "Don't polish the
 * renderers." Phase 3 polish: animations, draggable items, hover
 * tooltips, axis tick marks, item-clustering disambiguation.
 */

import { useState } from "react";

export type Quadrant = "bottom_left" | "bottom_right" | "top_left" | "top_right";

export interface TwoByTwoItemData {
  name: string;
  quadrant: Quadrant;
  rationale: string;
  evidence_citations: string[];
}

export interface TwoByTwoMatrixData {
  title: string;
  x_axis_label: string;
  x_axis_low_label: string;
  x_axis_high_label: string;
  y_axis_label: string;
  y_axis_low_label: string;
  y_axis_high_label: string;
  items: TwoByTwoItemData[];
  interpretation: string;
}

export interface TwoByTwoMatrixProps {
  data: TwoByTwoMatrixData;
}

const QUADRANT_ORDER: Quadrant[] = ["top_left", "top_right", "bottom_left", "bottom_right"];

// Lightweight extension type — we tag items with their original index
// before partitioning by quadrant so the click handler can deep-link
// back to the right entry.
type IndexedItem = TwoByTwoItemData & { __index: number };

function QuadrantCell({
  quadrant,
  items,
  onSelect,
}: {
  quadrant: Quadrant;
  items: IndexedItem[];
  onSelect: (index: number) => void;
}) {
  return (
    <div
      data-testid={`two-by-two-cell-${quadrant}`}
      className="min-h-[120px] border border-argus-border-subtle bg-surface p-2 first:border-r-0 last:border-t-0"
    >
      <ul className="space-y-1">
        {items.map((item, idx) => (
          <li key={`${quadrant}-${idx}`}>
            <button
              type="button"
              onClick={() => onSelect(item.__index)}
              className="w-full rounded border border-argus-border-subtle bg-elevated px-2 py-1 text-left text-[12px] text-argus-primary hover:bg-argus-firm-bg"
              data-testid="two-by-two-item"
            >
              <div className="font-semibold">{item.name}</div>
              <div className="line-clamp-2 text-[10px] text-argus-tertiary">{item.rationale}</div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TwoByTwoMatrix({ data }: TwoByTwoMatrixProps) {
  const [selected, setSelected] = useState<number | null>(null);

  const indexed: IndexedItem[] = data.items.map((item, idx) => ({ ...item, __index: idx }));
  const byQuadrant: Record<Quadrant, IndexedItem[]> = {
    top_left: indexed.filter((i) => i.quadrant === "top_left"),
    top_right: indexed.filter((i) => i.quadrant === "top_right"),
    bottom_left: indexed.filter((i) => i.quadrant === "bottom_left"),
    bottom_right: indexed.filter((i) => i.quadrant === "bottom_right"),
  };

  const selectedItem = selected !== null ? data.items[selected] : null;

  return (
    <section
      data-testid="two-by-two-matrix"
      className="rounded-md border border-argus-border-subtle bg-surface p-4"
    >
      <header className="mb-3">
        <h3 className="font-serif text-[16px] font-semibold text-argus-primary">{data.title}</h3>
      </header>

      <div className="grid grid-cols-[64px_1fr] gap-2">
        {/* Y-axis labels column */}
        <div className="flex flex-col items-center justify-between py-2 text-[10px] uppercase tracking-wide text-argus-tertiary">
          <span data-testid="y-axis-high">{data.y_axis_high_label}</span>
          <span className="rotate-180 [writing-mode:vertical-rl]" data-testid="y-axis-label">
            {data.y_axis_label}
          </span>
          <span data-testid="y-axis-low">{data.y_axis_low_label}</span>
        </div>

        {/* The 2x2 grid itself */}
        <div className="grid grid-cols-2 grid-rows-2">
          {QUADRANT_ORDER.map((q) => (
            <QuadrantCell key={q} quadrant={q} items={byQuadrant[q]} onSelect={setSelected} />
          ))}
        </div>
      </div>

      {/* X-axis row: low label, axis label, high label */}
      <div className="ml-[64px] mt-1 flex items-center justify-between text-[10px] uppercase tracking-wide text-argus-tertiary">
        <span data-testid="x-axis-low">{data.x_axis_low_label}</span>
        <span data-testid="x-axis-label">{data.x_axis_label}</span>
        <span data-testid="x-axis-high">{data.x_axis_high_label}</span>
      </div>

      <p className="mt-3 text-[13px] leading-relaxed text-argus-secondary" data-testid="interpretation">
        {data.interpretation}
      </p>

      {/* Detail panel — appears when an item is selected. Functional, not modal. */}
      {selectedItem ? (
        <aside
          data-testid="two-by-two-detail"
          className="mt-3 rounded border border-argus-border-subtle bg-elevated p-3"
        >
          <div className="flex items-baseline justify-between">
            <h4 className="font-serif text-[13px] font-semibold text-argus-primary">{selectedItem.name}</h4>
            <button
              type="button"
              onClick={() => setSelected(null)}
              className="text-[10px] uppercase tracking-wide text-argus-tertiary hover:text-argus-primary"
            >
              Close
            </button>
          </div>
          <p className="mt-1 text-[12px] text-argus-secondary">{selectedItem.rationale}</p>
          <div className="mt-2 flex flex-wrap gap-1">
            {selectedItem.evidence_citations.map((cid, i) => (
              <span
                key={`${cid}-${i}`}
                className="rounded border border-argus-border-subtle bg-surface px-1.5 py-0.5 font-mono text-[10px] text-argus-tertiary"
              >
                {cid}
              </span>
            ))}
          </div>
        </aside>
      ) : null}
    </section>
  );
}
