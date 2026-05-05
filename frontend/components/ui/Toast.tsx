"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export type ToastVariant = "success" | "error" | "info";

export interface Toast {
  id: string;
  message: string;
  variant: ToastVariant;
  /** Auto-dismiss after this many ms; 0 = sticky. Defaults to 4000. */
  durationMs?: number;
}

interface ToastContextValue {
  toast: (message: string, opts?: { variant?: ToastVariant; durationMs?: number }) => void;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

/**
 * Lightweight global toast system. Drop <ToastProvider> high in the tree
 * and call useToast().toast("message") from anywhere underneath.
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: string) => {
    const t = timers.current.get(id);
    if (t) {
      clearTimeout(t);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback<ToastContextValue["toast"]>(
    (message, opts) => {
      const id = `t-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const next: Toast = {
        id,
        message,
        variant: opts?.variant ?? "info",
        durationMs: opts?.durationMs ?? 4000,
      };
      setToasts((prev) => [...prev, next]);
      if (next.durationMs && next.durationMs > 0) {
        const handle = setTimeout(() => dismiss(id), next.durationMs);
        timers.current.set(id, handle);
      }
    },
    [dismiss],
  );

  useEffect(() => {
    const map = timers.current;
    return () => {
      map.forEach((t) => clearTimeout(t));
      map.clear();
    };
  }, []);

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // No-op fallback: lets components call useToast() outside the provider safely.
    return {
      toast: () => undefined,
      dismiss: () => undefined,
    };
  }
  return ctx;
}

const VARIANT_TONE: Record<ToastVariant, string> = {
  success: "border-argus-firm-border bg-argus-firm-bg text-argus-firm",
  error: "border-argus-contested-border bg-argus-contested-bg text-argus-contested",
  info: "border-argus-border-moderate bg-surface text-argus-primary",
};

const VARIANT_LABEL: Record<ToastVariant, string> = {
  success: "Success",
  error: "Error",
  info: "Info",
};

function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed bottom-4 right-4 z-[100] flex max-w-sm flex-col gap-2"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`pointer-events-auto flex items-start gap-3 rounded-sm border px-3 py-2 shadow-popover ${VARIANT_TONE[t.variant]}`}
        >
          <span aria-hidden className="mt-0.5 inline-block h-2 w-2 rounded-full bg-current" />
          <div className="min-w-0 flex-1">
            <div className="argus-label" style={{ color: "currentColor" }}>
              {VARIANT_LABEL[t.variant]}
            </div>
            <div className="mt-0.5 text-[12px] leading-snug">{t.message}</div>
          </div>
          <button
            type="button"
            onClick={() => onDismiss(t.id)}
            aria-label="Dismiss"
            className="rounded-sm p-0.5 text-current opacity-70 hover:opacity-100"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden>
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  );
}
