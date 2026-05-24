"use client";

import { useCallback, useEffect, useState } from "react";

import {
  NOTIFICATION_TYPE_LABEL,
  NotificationType,
  PreferenceEntry,
  getNotificationPreferences,
  resetNotificationPreferences,
  updateNotificationPreferences,
} from "@/lib/api/notifications";

/**
 * Per-type in-app + email toggles. Edits are batched — the user
 * flips toggles, the dirty entries collect locally, and "Save"
 * upserts them all in one PUT.
 *
 * "Reset to defaults" wipes every stored row and falls back to
 * dispatcher defaults (W18/D1 :func:`default_preference`).
 */
export default function NotificationPreferences() {
  const [rows, setRows] = useState<PreferenceEntry[] | null>(null);
  const [dirty, setDirty] = useState<Record<NotificationType, PreferenceEntry>>(
    {} as Record<NotificationType, PreferenceEntry>,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const r = await getNotificationPreferences();
      setRows(r.preferences);
      setDirty({} as Record<NotificationType, PreferenceEntry>);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const merged: PreferenceEntry[] = (rows || []).map((r) => {
    const d = dirty[r.notification_type];
    return d ? { ...r, ...d } : r;
  });

  const handleToggle = (
    nt: NotificationType, channel: "in_app" | "email", value: boolean,
  ) => {
    const base = (rows || []).find((r) => r.notification_type === nt);
    if (!base) return;
    const previous = dirty[nt];
    const draft: PreferenceEntry = {
      notification_type: nt,
      in_app: previous?.in_app ?? base.in_app,
      email: previous?.email ?? base.email,
    };
    draft[channel] = value;
    setDirty((d) => ({ ...d, [nt]: draft }));
  };

  const handleSave = async () => {
    const entries = Object.values(dirty);
    if (entries.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await updateNotificationPreferences(
        entries.map((e) => ({
          notification_type: e.notification_type,
          in_app: e.in_app,
          email: e.email,
        })),
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleReset = async () => {
    if (!confirm("Reset all notification preferences to defaults?")) return;
    setBusy(true);
    setError(null);
    try {
      await resetNotificationPreferences();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const hasDirty = Object.keys(dirty).length > 0;

  return (
    <section
      data-testid="notification-preferences"
      style={{
        background: "white",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <header style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
            Notification preferences
          </h2>
          <p style={{ margin: 0, fontSize: 11, color: "#6b7280" }}>
            Choose which notifications reach you in-app and via email.
          </p>
        </div>
        <button
          type="button"
          onClick={handleReset}
          disabled={busy}
          data-testid="notification-preferences-reset"
          style={{
            background: "transparent",
            border: 0,
            padding: 0,
            color: "#6b7280",
            fontSize: 11,
            cursor: busy ? "not-allowed" : "pointer",
          }}
        >
          Reset to defaults
        </button>
      </header>

      {error && (
        <div
          data-testid="notification-preferences-error"
          style={{
            padding: "6px 8px",
            background: "#fee2e2",
            color: "#991b1b",
            border: "1px solid #fecaca",
            borderRadius: 6,
            fontSize: 12,
          }}
        >
          {error}
        </div>
      )}

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ textAlign: "left", color: "#6b7280" }}>
            <th style={{ padding: "4px 0", fontWeight: 500 }}>Type</th>
            <th style={{ padding: "4px 0", fontWeight: 500, width: 70 }}>In-app</th>
            <th style={{ padding: "4px 0", fontWeight: 500, width: 70 }}>Email</th>
          </tr>
        </thead>
        <tbody>
          {rows === null && (
            <tr><td colSpan={3} style={{ color: "#6b7280" }}>Loading…</td></tr>
          )}
          {merged.map((row) => (
            <tr
              key={row.notification_type}
              data-testid={`notification-pref-${row.notification_type}`}
              style={{ borderTop: "1px solid #f3f4f6" }}
            >
              <td style={{ padding: "8px 0", color: "#111827" }}>
                {NOTIFICATION_TYPE_LABEL[row.notification_type as NotificationType]
                  ?? row.notification_type}
              </td>
              <td style={{ padding: "8px 0" }}>
                <input
                  type="checkbox"
                  checked={row.in_app}
                  disabled={busy}
                  onChange={(e) => handleToggle(
                    row.notification_type as NotificationType,
                    "in_app", e.target.checked,
                  )}
                  data-testid={`notification-pref-${row.notification_type}-in_app`}
                />
              </td>
              <td style={{ padding: "8px 0" }}>
                <input
                  type="checkbox"
                  checked={row.email}
                  disabled={busy}
                  onChange={(e) => handleToggle(
                    row.notification_type as NotificationType,
                    "email", e.target.checked,
                  )}
                  data-testid={`notification-pref-${row.notification_type}-email`}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <button
          type="button"
          onClick={() => setDirty({} as Record<NotificationType, PreferenceEntry>)}
          disabled={!hasDirty || busy}
          data-testid="notification-preferences-cancel"
          style={{
            padding: "6px 12px",
            background: "transparent",
            border: "1px solid #d1d5db",
            borderRadius: 6,
            fontSize: 12,
            cursor: hasDirty && !busy ? "pointer" : "not-allowed",
            color: "#6b7280",
          }}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={!hasDirty || busy}
          data-testid="notification-preferences-save"
          style={{
            padding: "6px 12px",
            background: hasDirty ? "#111827" : "#9ca3af",
            color: "white",
            border: 0,
            borderRadius: 6,
            fontSize: 12,
            cursor: hasDirty && !busy ? "pointer" : "not-allowed",
          }}
        >
          Save
        </button>
      </div>
    </section>
  );
}
