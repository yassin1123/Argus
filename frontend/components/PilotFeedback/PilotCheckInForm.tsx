"use client";

// Weekly pilot check-in form — Phase 5 / Week 24 / Day 3.
// Rendered in-app for the firm_admin. 5-7 structured questions; the
// question set comes from the backend so it can evolve without a
// frontend deploy.

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  getCheckinForm,
  submitCheckin,
  type CheckinQuestion,
} from "@/lib/api/pilotFeedback";

export default function PilotCheckInForm({ onSubmitted }: { onSubmitted?: () => void }) {
  const [questions, setQuestions] = useState<CheckinQuestion[]>([]);
  const [responses, setResponses] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getCheckinForm()
      .then((r) => setQuestions(r.questions))
      .catch((e) => setErr((e as Error).message))
      .finally(() => setLoading(false));
  }, []);

  const setAnswer = (id: string, value: unknown) =>
    setResponses((r) => ({ ...r, [id]: value }));

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await submitCheckin(responses);
      setDone(true);
      onSubmitted?.();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <p className="p-4 text-sm text-argus-secondary">Loading check-in…</p>;
  if (done) {
    return (
      <p className="p-4 text-sm text-emerald-700">
        Thanks — this week's check-in is recorded.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <header>
        <h2 className="text-base font-semibold text-argus-primary">Weekly pilot check-in</h2>
        <p className="text-sm text-argus-secondary">
          Two minutes. It's how the product gets better for you.
        </p>
      </header>
      {questions.map((q) => (
        <div key={q.id}>
          <label className="mb-1 block text-sm font-medium text-argus-primary">{q.prompt}</label>
          {q.type === "text" && (
            <textarea
              className="w-full rounded-argus border border-argus-border-subtle px-3 py-2 text-sm"
              rows={2}
              onChange={(e) => setAnswer(q.id, e.target.value)}
            />
          )}
          {q.type === "scale_1_5" && (
            <div className="flex gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setAnswer(q.id, n)}
                  className={`h-8 w-8 rounded-argus border text-sm ${
                    responses[q.id] === n
                      ? "border-argus-accent bg-elevated text-argus-primary"
                      : "border-argus-border-subtle text-argus-secondary"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          )}
          {q.type === "yes_no" && (
            <div className="flex gap-2">
              {["yes", "no"].map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setAnswer(q.id, v)}
                  className={`rounded-argus border px-3 py-1 text-sm capitalize ${
                    responses[q.id] === v
                      ? "border-argus-accent bg-elevated text-argus-primary"
                      : "border-argus-border-subtle text-argus-secondary"
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
      {err && <p className="text-sm text-red-700">{err}</p>}
      <Button onClick={submit} disabled={busy}>
        {busy ? "Submitting…" : "Submit check-in"}
      </Button>
    </div>
  );
}
