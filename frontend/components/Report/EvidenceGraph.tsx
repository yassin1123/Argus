"use client";

import { useEffect, useMemo, useState } from "react";

import { getEvidenceGraph } from "@/lib/api";
import { useSelection } from "@/lib/SelectionContext";
import type { EvidenceGraph, EvidenceGraphNode } from "@/lib/types";

const LANE_WIDTH = 220;
const LANE_GAP = 56;
const NODE_HEIGHT = 64;
const NODE_GAP = 14;
const TOP_PAD = 52;
const SIDE_PAD = 20;

type Pos = { x: number; y: number };

function verdictTone(node: EvidenceGraphNode): {
  border: string;
  bg: string;
  dot: string;
  label: string;
} {
  if (node.type === "claim") {
    const v = (node.verifier_verdict || "unknown").toLowerCase();
    if (v === "supported")
      return {
        border: "border-argus-success-border",
        bg: "bg-argus-success-subtle",
        dot: "bg-argus-success",
        label: "supported",
      };
    if (v === "weak")
      return {
        border: "border-argus-warning-border",
        bg: "bg-argus-warning-subtle",
        dot: "bg-argus-warning",
        label: "weak",
      };
    if (v === "unsupported" || v === "overstates")
      return {
        border: "border-argus-danger-border",
        bg: "bg-argus-danger-subtle",
        dot: "bg-argus-danger",
        label: v,
      };
    return {
      border: "border-argus-border-subtle",
      bg: "bg-argus-neutral-subtle",
      dot: "bg-argus-neutral",
      label: "unverified",
    };
  }
  if (node.type === "evidence") {
    if (node.is_inference)
      return {
        border: "border-argus-border-subtle",
        bg: "bg-argus-neutral-subtle",
        dot: "bg-argus-neutral",
        label: "inference",
      };
    const c = (node.confidence || "medium").toLowerCase();
    if (c === "high")
      return {
        border: "border-argus-info-border",
        bg: "bg-argus-info-subtle",
        dot: "bg-argus-accent",
        label: "high confidence",
      };
    return {
      border: "border-argus-border-subtle",
      bg: "bg-argus-neutral-subtle",
      dot: "bg-argus-neutral",
      label: c,
    };
  }
  // source
  return {
    border: "border-argus-border-moderate",
    bg: "bg-elevated",
    dot: "bg-argus-secondary",
    label: node.source_type || "source",
  };
}

function StatPill({ label, count, tone }: { label: string; count: number; tone: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-argus-sm border border-argus-border-subtle bg-surface px-2 py-1 text-[11px] text-argus-secondary">
      <span className={`inline-block h-2 w-2 rounded-full ${tone}`} aria-hidden />
      <span className="font-medium text-argus-primary">{count}</span>
      <span>{label}</span>
    </span>
  );
}

function NodeCard({
  node,
  pos,
  selected,
  dimmed,
  onClick,
  onHover,
}: {
  node: EvidenceGraphNode;
  pos: Pos;
  selected: boolean;
  dimmed: boolean;
  onClick: () => void;
  onHover?: (hovering: boolean) => void;
}) {
  const tone = verdictTone(node);
  const ring = selected ? "ring-2 ring-argus-accent" : "";
  const opacity = dimmed ? "opacity-30" : "opacity-100";
  const inRec = node.in_recommendation
    ? "shadow-argus border-argus-accent"
    : "";

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => onHover?.(true)}
      onMouseLeave={() => onHover?.(false)}
      style={{
        position: "absolute",
        left: pos.x,
        top: pos.y,
        width: LANE_WIDTH,
        height: NODE_HEIGHT,
      }}
      className={`group flex flex-col justify-center rounded-argus-md border ${tone.border} ${tone.bg} ${ring} ${opacity} ${inRec} px-3 py-2 text-left transition-opacity hover:opacity-100`}
    >
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${tone.dot}`} aria-hidden />
        <span className="truncate text-[11px] font-medium uppercase tracking-wide text-argus-tertiary">
          {node.type}
          {node.in_recommendation ? " · in recommendation" : ""}
        </span>
        <span className="ml-auto truncate text-[10px] text-argus-tertiary">{tone.label}</span>
      </div>
      <div className="mt-1 line-clamp-2 text-[12px] leading-snug text-argus-primary">
        {node.label}
      </div>
    </button>
  );
}

function GraphLegend({ stats }: { stats: EvidenceGraph["stats"] }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <StatPill label="claims" count={stats.claims} tone="bg-argus-accent" />
      <StatPill label="supported" count={stats.supported} tone="bg-argus-success" />
      <StatPill label="weak" count={stats.weak} tone="bg-argus-warning" />
      <StatPill label="unsupported" count={stats.unsupported} tone="bg-argus-danger" />
      <StatPill label="evidence" count={stats.evidence} tone="bg-argus-secondary" />
      <StatPill label="sources" count={stats.sources} tone="bg-argus-neutral" />
    </div>
  );
}

function NodeDetail({ node }: { node: EvidenceGraphNode }) {
  return (
    <aside className="rounded-argus-md border border-argus-border-subtle bg-surface p-4">
      <div className="text-[11px] font-medium uppercase tracking-wide text-argus-tertiary">
        {node.type}
      </div>
      <div className="mt-1 text-sm font-medium text-argus-primary">{node.label}</div>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[12px]">
        {node.type === "claim" && (
          <>
            <dt className="text-argus-tertiary">verdict</dt>
            <dd className="text-argus-primary">
              {node.verifier_verdict || "unverified"}
            </dd>
            <dt className="text-argus-tertiary">support</dt>
            <dd className="text-argus-primary">{node.support_type || "—"}</dd>
            <dt className="text-argus-tertiary">evidence</dt>
            <dd className="text-argus-primary">{node.evidence_count ?? 0} object(s)</dd>
            {node.in_recommendation ? (
              <>
                <dt className="text-argus-tertiary">role</dt>
                <dd className="text-argus-primary">in recommendation</dd>
              </>
            ) : null}
          </>
        )}
        {node.type === "evidence" && (
          <>
            <dt className="text-argus-tertiary">confidence</dt>
            <dd className="text-argus-primary">{node.confidence || "—"}</dd>
            <dt className="text-argus-tertiary">type</dt>
            <dd className="text-argus-primary">
              {node.is_inference ? "inference" : node.source_type || "—"}
            </dd>
            {node.source_title ? (
              <>
                <dt className="text-argus-tertiary">source</dt>
                <dd className="truncate text-argus-primary">{node.source_title}</dd>
              </>
            ) : null}
            {node.source_url ? (
              <>
                <dt className="text-argus-tertiary">link</dt>
                <dd className="truncate">
                  <a
                    href={node.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-argus-accent hover:underline"
                  >
                    {node.source_url}
                  </a>
                </dd>
              </>
            ) : null}
          </>
        )}
        {node.type === "source" && (
          <>
            <dt className="text-argus-tertiary">cited by</dt>
            <dd className="text-argus-primary">{node.evidence_count ?? 0} evidence object(s)</dd>
            {node.url ? (
              <>
                <dt className="text-argus-tertiary">link</dt>
                <dd className="truncate">
                  <a
                    href={node.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-argus-accent hover:underline"
                  >
                    {node.url}
                  </a>
                </dd>
              </>
            ) : null}
          </>
        )}
      </dl>
      {node.quote ? (
        <blockquote className="mt-3 border-l-2 border-argus-border-moderate pl-3 text-[12px] italic text-argus-secondary">
          “{node.quote}”
        </blockquote>
      ) : null}
    </aside>
  );
}

export default function EvidenceGraph({ sessionId }: { sessionId: string }) {
  const [graph, setGraph] = useState<EvidenceGraph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const { selectedClaimId, setSelectedClaim, setHoveredClaim } = useSelection();

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const data = await getEvidenceGraph(sessionId);
        if (alive) setGraph(data);
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : "Failed to load graph");
      }
    })();
    return () => {
      alive = false;
    };
  }, [sessionId]);

  // Mirror the global selection — if a claim is selected from elsewhere, highlight it here.
  useEffect(() => {
    if (selectedClaimId) setSelected(selectedClaimId);
  }, [selectedClaimId]);

  const layout = useMemo(() => {
    if (!graph) return { positions: new Map<string, Pos>(), width: 0, height: 0 };
    const claims = graph.nodes.filter((n) => n.type === "claim");
    const evidence = graph.nodes.filter((n) => n.type === "evidence");
    const sources = graph.nodes.filter((n) => n.type === "source");
    const positions = new Map<string, Pos>();
    const place = (list: EvidenceGraphNode[], laneIndex: number) => {
      const x = SIDE_PAD + laneIndex * (LANE_WIDTH + LANE_GAP);
      list.forEach((n, i) => {
        positions.set(n.id, { x, y: TOP_PAD + i * (NODE_HEIGHT + NODE_GAP) });
      });
    };
    place(claims, 0);
    place(evidence, 1);
    place(sources, 2);
    const tallest = Math.max(claims.length, evidence.length, sources.length, 1);
    return {
      positions,
      width: SIDE_PAD * 2 + 3 * LANE_WIDTH + 2 * LANE_GAP,
      height: TOP_PAD + tallest * (NODE_HEIGHT + NODE_GAP) + 32,
    };
  }, [graph]);

  const connectedIds = useMemo(() => {
    if (!graph || !selected) return null;
    const set = new Set<string>([selected]);
    for (const e of graph.edges) {
      if (e.from === selected) set.add(e.to);
      if (e.to === selected) set.add(e.from);
    }
    return set;
  }, [graph, selected]);

  if (error) {
    return (
      <div className="rounded-argus-md border border-argus-danger-border bg-argus-danger-subtle p-4 text-sm text-argus-danger">
        {error}
      </div>
    );
  }

  if (!graph) {
    return (
      <div className="rounded-argus-md border border-argus-border-subtle bg-surface p-6 text-sm text-argus-tertiary">
        Loading evidence graph…
      </div>
    );
  }

  if (graph.nodes.length === 0) {
    return (
      <div className="rounded-argus-md border border-argus-border-subtle bg-surface p-6 text-sm text-argus-tertiary">
        No evidence graph available yet. Run the pipeline to generate one.
      </div>
    );
  }

  const selectedNode = selected ? graph.nodes.find((n) => n.id === selected) || null : null;

  return (
    <section className="space-y-4">
      <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="font-serif text-lg text-argus-primary">Evidence graph</h2>
          <p className="mt-1 text-[12px] text-argus-tertiary">
            Click a claim, evidence object, or source to see what it connects to.
          </p>
        </div>
        <GraphLegend stats={graph.stats} />
      </header>

      <div className="space-y-3">
        <div className="overflow-x-auto rounded-argus-md border border-argus-border-subtle bg-canvas">
          <div
            style={{ width: layout.width, height: layout.height, position: "relative" }}
          >
            <div className="absolute inset-x-0 top-3 grid grid-cols-3 gap-0 px-6">
              <div className="text-[11px] font-medium uppercase tracking-wider text-argus-tertiary">
                Claims
              </div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-argus-tertiary">
                Evidence
              </div>
              <div className="text-[11px] font-medium uppercase tracking-wider text-argus-tertiary">
                Sources
              </div>
            </div>

            <svg
              width={layout.width}
              height={layout.height}
              className="pointer-events-none absolute inset-0"
              aria-hidden
            >
              {graph.edges.map((edge, i) => {
                const a = layout.positions.get(edge.from);
                const b = layout.positions.get(edge.to);
                if (!a || !b) return null;
                const x1 = a.x + LANE_WIDTH;
                const y1 = a.y + NODE_HEIGHT / 2;
                const x2 = b.x;
                const y2 = b.y + NODE_HEIGHT / 2;
                const cx = (x1 + x2) / 2;
                const path = `M ${x1} ${y1} C ${cx} ${y1}, ${cx} ${y2}, ${x2} ${y2}`;
                const isHighlighted =
                  connectedIds && (connectedIds.has(edge.from) && connectedIds.has(edge.to));
                const stroke =
                  edge.kind === "contradicts"
                    ? "var(--semantic-danger)"
                    : "var(--border-strong)";
                const opacity = connectedIds ? (isHighlighted ? 1 : 0.15) : 0.55;
                return (
                  <path
                    key={`e${i}`}
                    d={path}
                    fill="none"
                    stroke={stroke}
                    strokeWidth={isHighlighted ? 2 : 1.25}
                    opacity={opacity}
                  />
                );
              })}
            </svg>

            {graph.nodes.map((n) => {
              const pos = layout.positions.get(n.id);
              if (!pos) return null;
              const isSelected = selected === n.id;
              const isDimmed =
                connectedIds !== null && !connectedIds.has(n.id);
              return (
                <NodeCard
                  key={n.id}
                  node={n}
                  pos={pos}
                  selected={isSelected}
                  dimmed={isDimmed}
                  onClick={() => {
                    const next = isSelected ? null : n.id;
                    setSelected(next);
                    // Mirror claim selections into the global spine.
                    if (n.type === "claim") {
                      setSelectedClaim(next);
                    }
                  }}
                  onHover={(hovering) => {
                    if (n.type === "claim") {
                      setHoveredClaim(hovering ? n.id : null);
                    }
                  }}
                />
              );
            })}
          </div>
        </div>

        {selectedNode ? <NodeDetail node={selectedNode} /> : null}
      </div>
    </section>
  );
}
