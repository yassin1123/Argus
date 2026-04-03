"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { getChatHistory, sendChatMessage } from "@/lib/api";

type Turn = {
  id: string;
  role: string;
  content: string;
  turn_index: number;
  created_at?: string | null;
};

export default function ChatPage() {
  const params = useParams();
  const id = params.id as string;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFollowUp, setLastFollowUp] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await getChatHistory(id);
      setTurns(rows as Turn[]);
      setError(null);
    } catch {
      setError("Could not load chat history.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const send = async () => {
    const t = input.trim();
    if (!t || sending) return;
    setSending(true);
    setError(null);
    setInput("");
    try {
      const res = await sendChatMessage(id, t);
      setLastFollowUp(res.follow_up_question || "");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Send failed");
    } finally {
      setSending(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col px-4 py-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <Link
          href={`/sessions/${id}`}
          className="text-sm font-medium text-argus-accent hover:underline"
        >
          ← Workspace
        </Link>
        <span className="text-[11px] font-semibold uppercase tracking-wide text-argus-tertiary">
          Analyst chat
        </span>
      </div>

      {loading ? (
        <p className="text-sm text-argus-secondary">Loading…</p>
      ) : (
        <div className="flex-1 space-y-4 overflow-y-auto pb-24">
          {turns.length === 0 ? (
            <p className="rounded-[14px] border border-argus-border-subtle bg-surface p-4 text-sm text-argus-secondary">
              Ask a follow-up about this session. If deeper research is needed, Argus will run the pipeline in
              the background — watch progress on the workspace view.
            </p>
          ) : null}
          {turns.map((m) => (
            <div
              key={m.id}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-[16px] px-4 py-3 text-sm leading-relaxed ${
                  m.role === "user"
                    ? "bg-argus-accent text-white"
                    : "border border-argus-border-subtle bg-surface text-argus-primary"
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
        </div>
      )}

      {lastFollowUp ? (
        <button
          type="button"
          className="mb-2 rounded-full border border-argus-border-subtle bg-canvas px-3 py-1.5 text-left text-xs text-argus-secondary hover:bg-argus-neutral-subtle"
          onClick={() => setInput(lastFollowUp)}
        >
          Suggested: {lastFollowUp}
        </button>
      ) : null}

      {error ? <p className="mb-2 text-sm text-argus-danger">{error}</p> : null}

      <div className="fixed bottom-0 left-0 right-0 border-t border-argus-border-subtle bg-canvas/95 p-4 backdrop-blur-md">
        <div className="mx-auto flex max-w-3xl gap-2">
          <textarea
            className="min-h-[44px] flex-1 resize-none rounded-xl border border-argus-border-subtle bg-surface px-3 py-2 text-sm text-argus-primary placeholder:text-argus-tertiary focus:border-argus-accent focus:outline-none"
            placeholder="Message Argus…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={2}
          />
          <Button type="button" disabled={sending} onClick={() => void send()}>
            {sending ? "…" : "Send"}
          </Button>
        </div>
      </div>
    </main>
  );
}
