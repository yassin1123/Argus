"use client";

interface Props {
  /** Display name. Initials are derived from this. Falls back to
   *  the email's local part when name is blank. */
  name?: string;
  email?: string;
  /** Optional one-letter role suffix (e.g. "L" for lead) rendered
   *  as a small badge in the bottom-right corner. */
  roleBadge?: string;
  size?: number;
  /** Optional title (tooltip) override. */
  title?: string;
  /** Optional onClick for clickable avatars. */
  onClick?: () => void;
  testId?: string;
}

/**
 * Compact initials-circle avatar — no image dependency, deterministic
 * background colour per name so each teammate is visually identifiable
 * at a glance.
 *
 * No external image fetch is intentional (W17/D4 ships functional, not
 * polished; profile photos would mean a new storage path + an upload
 * surface, both Phase 5 work).
 */
export default function UserAvatar({
  name,
  email,
  roleBadge,
  size = 28,
  title,
  onClick,
  testId,
}: Props) {
  const label = (name || "").trim() || (email?.split("@")[0] ?? "?");
  const initials = _initials(label);
  const bg = _color(label);
  const tooltip = title ?? (name ? `${name}${email ? ` <${email}>` : ""}` : label);

  return (
    <span
      onClick={onClick}
      data-testid={testId}
      title={tooltip}
      aria-label={tooltip}
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: size,
        height: size,
        borderRadius: "50%",
        background: bg,
        color: "white",
        fontSize: Math.max(10, Math.floor(size * 0.4)),
        fontWeight: 600,
        flexShrink: 0,
        cursor: onClick ? "pointer" : "default",
        userSelect: "none",
      }}
    >
      {initials}
      {roleBadge && (
        <span
          style={{
            position: "absolute",
            right: -2,
            bottom: -2,
            background: "#111827",
            color: "white",
            border: "1.5px solid white",
            borderRadius: "50%",
            width: Math.max(12, Math.floor(size * 0.45)),
            height: Math.max(12, Math.floor(size * 0.45)),
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: Math.max(8, Math.floor(size * 0.28)),
            fontWeight: 700,
          }}
        >
          {roleBadge}
        </span>
      )}
    </span>
  );
}

function _initials(name: string): string {
  const parts = name.split(/[\s.@_-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Stable colour per name — hash → fixed palette so the same person
// always renders in the same colour, but new teammates spread across
// the palette.
const _PALETTE = [
  "#0ea5e9", "#6366f1", "#8b5cf6", "#ec4899", "#ef4444",
  "#f59e0b", "#10b981", "#14b8a6", "#84cc16", "#06b6d4",
];

function _color(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  }
  return _PALETTE[Math.abs(hash) % _PALETTE.length];
}
