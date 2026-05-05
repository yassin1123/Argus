"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { login } from "@/lib/api";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password);
      router.replace(next);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-[420px] flex-col justify-center px-6 py-16">
      <div className="mb-8">
        <h1 className="font-serif text-[36px] font-semibold text-argus-primary">Argus</h1>
        <p className="mt-1 text-[12px] uppercase tracking-[0.1em] text-argus-tertiary">
          Sign in to your workbench
        </p>
      </div>

      <form onSubmit={submit} className="space-y-4 rounded-argus-md border border-argus-border-subtle bg-surface p-6">
        <div>
          <label htmlFor="email" className="argus-label mb-1 block">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            className="w-full rounded-sm border border-argus-border-moderate bg-canvas px-2.5 py-2 text-[13px] text-argus-primary focus:border-argus-border-strong focus:outline-none"
          />
        </div>
        <div>
          <label htmlFor="password" className="argus-label mb-1 block">
            Password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            className="w-full rounded-sm border border-argus-border-moderate bg-canvas px-2.5 py-2 text-[13px] text-argus-primary focus:border-argus-border-strong focus:outline-none"
          />
        </div>
        {error ? (
          <p className="rounded-sm border border-argus-contested-border bg-argus-contested-bg px-2 py-1 text-[12px] text-argus-contested">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-sm border border-argus-border-strong bg-argus-primary px-3 py-2 text-[13px] font-semibold text-argus-inverse hover:opacity-90 disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-center text-[12px] text-argus-tertiary">
          New to Argus?{" "}
          <Link href="/register" className="font-medium text-argus-accent hover:underline">
            Create an account
          </Link>
        </p>
      </form>

      <p className="mt-4 text-center text-[10px] text-argus-quaternary">
        Demo login: demo@argus.local · demo-password
      </p>
    </main>
  );
}
