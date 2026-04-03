import Link from "next/link";
import { listSessions } from "@/lib/api";
import { SessionCard } from "@/components/sessions/SessionCard";

export const dynamic = "force-dynamic";

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="2" />
      <path d="M21 21l-4.35-4.35" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export default async function SessionsPage() {
  let sessions: Awaited<ReturnType<typeof listSessions>> = [];
  let err: string | null = null;
  try {
    sessions = await listSessions();
  } catch {
    err = "Could not reach API. Is the backend running?";
  }

  return (
    <main className="mx-auto max-w-[720px] px-4 py-12">
      <div className="mb-8 flex items-baseline justify-between">
        <h1 className="font-serif text-[28px] text-argus-primary">Sessions</h1>
        <Link
          href="/"
          className="text-sm text-argus-accent transition-colors hover:text-argus-primary"
        >
          + New analysis
        </Link>
      </div>
      {err && <p className="mb-4 text-sm text-argus-danger">{err}</p>}
      <div className="space-y-3">
        {sessions.map((s) => (
          <SessionCard key={s.id} s={s} />
        ))}
      </div>
      {sessions.length === 0 && !err && (
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="mb-6 flex h-16 w-16 items-center justify-center rounded-full bg-overlay">
            <SearchIcon className="text-argus-tertiary" />
          </div>
          <h2 className="font-serif text-xl text-argus-primary">No analyses yet</h2>
          <p className="mt-2 text-sm text-argus-tertiary">
            Start by asking a question that needs a structured answer.
          </p>
          <Link
            href="/"
            className="mt-6 rounded-[10px] bg-ink px-5 py-2.5 text-sm font-semibold text-white transition-colors duration-150 hover:bg-ink-muted"
          >
            Start first analysis
          </Link>
        </div>
      )}
    </main>
  );
}
