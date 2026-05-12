"use client";

/**
 * DeepeningHistory — Phase 2 / Week 9 / Day 2.
 *
 * Small expandable above the section picker. Lists prior deepening
 * runs on the engagement (newest first). Click any item → host
 * reopens the StatusPanel pointing at that deepening_id, so the
 * consultant can review the result.
 *
 * Auto-fetches on mount and on ``reloadKey`` change. The host bumps
 * ``reloadKey`` after each new trigger so the list refreshes
 * without prop-drilling a callback.
 */

import { useCallback, useEffect, useState } from "react";

import {
  Deepening,
  listDeepenings,
  sectionDisplayName,
} from "@/lib/api/sectionDeepening";

export interface DeepeningHistoryProps {
  sessionId: string;
  onOpenDeepening: (deepeningId: string, sectionPath: string) => void;
  /** Bump to force a reload (e.g. after triggering a new deepening). */
  reloadKey?: number;
}

export default function DeepeningHistory({
  sessionId,
  onOpenDeepening,
  reloadKey = 0,
}: DeepeningHistoryProps) {
  const [items, setItems] = useState<Deepening[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const list = await listDeepenings(sessionId);
      setItems(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [sessionId]);

  useEffect(() => {
    void reload();
  }, [reload, reloadKey]);

  if (items.length === 0 && !error) return null;

  return (
    <section
      data-testid="deepening-history"
      className="mb-3 rounded border border-argus-border-subtle bg-surface"
    >
      <button
        type="button"
        data-testid="history-toggle"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-[12px] text-argus-secondary hover:bg-elevated"
        aria-expanded={expanded}
      >
        <span>
          Previous deepenings ({items.length})
        </span>
        <span className="font-mono text-[10px] text-argus-tertiary">
          {expanded ? "▾" : "▸"}
        </span>
      </button>
      {expanded ? (
        <ul data-testid="history-list" className="border-t border-argus-border-subtle">
          {items.map((d) => (
            <li key={d.id} data-testid={`history-item-${d.id}`}>
              <button
                type="button"
                onClick={() => onOpenDeepening(d.id, d.section_path)}
                className="flex w-full items-baseline justify-between gap-2 px-3 py-1.5 text-left text-[11px] text-argus-secondary hover:bg-elevated"
              >
                <span className="font-mono text-[10px] text-argus-tertiary">
                  {new Date(d.created_at).toLocaleString()}
                </span>
                <span className="flex-1 truncate text-argus-primary">
                  {sectionDisplayName(d.section_path)}
                </span>
                <span
                  data-testid={`history-status-${d.id}`}
                  data-status={d.status}
                  className={
                    d.status === "complete"
                      ? "text-argus-firm"
                      : d.status === "failed"
                      ? "text-argus-contested"
                      : "text-argus-tertiary"
                  }
                >
                  {d.status}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <p data-testid="history-error" className="px-3 py-2 text-[11px] text-argus-contested">
          {error}
        </p>
      ) : null}
    </section>
  );
}
