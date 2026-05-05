"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import {
  generateIntakeQuestions,
  getSession,
  runSession,
  submitIntakeAnswers,
} from "@/lib/api";

type IntakeQ = {
  id: string;
  question: string;
  why?: string;
  placeholder?: string;
};

export default function IntakePage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [questions, setQuestions] = useState<IntakeQ[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const session = await getSession(id);
      const existingQ = session.intake_questions as IntakeQ[] | undefined;
      const existingA = session.intake_answers as { id: string; answer: string }[] | undefined;
      if (existingA && existingA.length > 0) {
        router.replace(`/sessions/${id}`);
        return;
      }
      if (existingQ && existingQ.length > 0) {
        setQuestions(existingQ);
        const map: Record<string, string> = {};
        for (const a of existingA || []) {
          map[a.id] = a.answer;
        }
        setAnswers(map);
        setStep(0);
        return;
      }
      const data = await generateIntakeQuestions(id);
      setQuestions((data.questions as IntakeQ[]) || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load intake");
    } finally {
      setLoading(false);
    }
  }, [id, router]);

  useEffect(() => {
    void load();
  }, [load]);

  const total = questions.length;
  const current = questions[step];
  const progress = total ? Math.round(((step + 1) / total) * 100) : 0;

  const handleNext = () => {
    if (step < total - 1) setStep((s) => s + 1);
  };

  const handleBack = () => {
    if (step > 0) setStep((s) => s - 1);
  };

  const handleFinish = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const payload = questions.map((q) => ({
        id: q.id,
        answer: (answers[q.id] || "").trim(),
      }));
      await submitIntakeAnswers(id, payload);
      await runSession(id);
      router.replace(`/sessions/${id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submit failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <main className="mx-auto flex min-h-[60vh] max-w-lg flex-col items-center justify-center px-4">
        <p className="text-sm text-argus-secondary">Preparing a few questions…</p>
      </main>
    );
  }

  if (error && !questions.length) {
    return (
      <main className="mx-auto max-w-lg px-4 py-16">
        <p className="text-argus-danger">{error}</p>
        <Button variant="ghost" className="mt-4" onClick={() => void load()}>
          Retry
        </Button>
      </main>
    );
  }

  if (!total) {
    return (
      <main className="mx-auto max-w-lg px-4 py-16">
        <p className="text-argus-secondary">No questions generated. Continue to analysis.</p>
        <Button className="mt-4" onClick={() => router.replace(`/sessions/${id}`)}>
          Continue
        </Button>
      </main>
    );
  }

  return (
    <main className="mx-auto min-h-[70vh] max-w-lg px-4 py-10">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-argus-tertiary">
        Context · {step + 1} / {total}
      </p>
      <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-argus-neutral-subtle">
        <div
          className="h-full rounded-full bg-argus-accent transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="mt-10 rounded-[20px] border border-argus-border-subtle bg-surface p-6 shadow-argus-sm">
        <h1 className="font-serif text-xl font-semibold leading-snug text-argus-primary">
          {current.question}
        </h1>
        {current.why ? (
          <p className="mt-3 text-sm leading-relaxed text-argus-secondary">{current.why}</p>
        ) : null}
        <label className="mt-6 block">
          <span className="sr-only">Your answer</span>
          <textarea
            className="mt-2 min-h-[100px] w-full resize-y rounded-xl border border-argus-border-subtle bg-canvas px-3 py-2 text-sm text-argus-primary placeholder:text-argus-tertiary focus:border-argus-accent focus:outline-none focus:ring-1 focus:ring-argus-accent"
            placeholder={current.placeholder || "Your answer…"}
            value={answers[current.id] || ""}
            onChange={(e) =>
              setAnswers((prev) => ({ ...prev, [current.id]: e.target.value }))
            }
          />
        </label>
      </div>

      {error ? <p className="mt-4 text-sm text-argus-danger">{error}</p> : null}

      <div className="mt-8 flex items-center justify-between gap-3">
        <Button variant="ghost" type="button" onClick={handleBack} disabled={step === 0}>
          Back
        </Button>
        {step < total - 1 ? (
          <Button type="button" onClick={handleNext}>
            Next
          </Button>
        ) : (
          <Button type="button" disabled={submitting} onClick={() => void handleFinish()}>
            {submitting ? "Starting…" : "Run analysis"}
          </Button>
        )}
      </div>
    </main>
  );
}
