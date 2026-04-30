"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { register } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      await register(email.trim(), password, fullName.trim());
      router.replace("/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
      setBusy(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-[420px] flex-col justify-center px-6 py-16">
      <div className="mb-8">
        <h1 className="font-serif text-[36px] font-semibold text-argus-primary">Argus</h1>
        <p className="mt-1 text-[12px] uppercase tracking-[0.1em] text-argus-tertiary">
          Create your workbench account
        </p>
      </div>

      <form onSubmit={submit} className="space-y-4 rounded-argus-md border border-argus-border-subtle bg-surface p-6">
        <div>
          <label htmlFor="full_name" className="argus-label mb-1 block">
            Full name
          </label>
          <input
            id="full_name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            autoComplete="name"
            className="w-full rounded-sm border border-argus-border-moderate bg-canvas px-2.5 py-2 text-[13px] text-argus-primary focus:border-argus-border-strong focus:outline-none"
          />
        </div>
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
            Password <span className="lowercase tracking-normal text-argus-quaternary">· 8+ chars</span>
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete="new-password"
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
          {busy ? "Creating account…" : "Create account"}
        </button>
        <p className="text-center text-[12px] text-argus-tertiary">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-argus-accent hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </main>
  );
}
